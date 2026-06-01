# linkedin/pipeline/pools.py
"""Pool management via composable generators.

Three generators chain via next(upstream, None):

    find_candidate() = next(ready_source, None)
                            |
                  ready_source  <- pulls from qualify_source
                            |
                 qualify_source  <- pulls from search_source
                  (keeps searching until P > 0.5 candidates exist in exploit mode)
                            |
                  search_source  <- yields keywords (never truly exhausts)

Each qualify_source iteration produces exactly one label, which shifts the GP
model — preventing the infinite-search-without-qualifying bug.
"""
from __future__ import annotations

import logging
from typing import Generator

import numpy as np

from linkedin.conf import CAMPAIGN_CONFIG
from linkedin.pipeline_config import get_campaign_config
from linkedin.ml.qualifier import BayesianQualifier
from linkedin.pipeline.qualify import fetch_qualification_candidates, run_qualification
from linkedin.pipeline.ready_pool import find_ready_candidate, promote_to_ready
from linkedin.pipeline.search import run_search

logger = logging.getLogger(__name__)


def _needs_search(qualifier: BayesianQualifier, candidates) -> bool:
    """True only in exploit mode when no candidate meets the adaptive threshold.

    Effective threshold = max(0, base - 1/sqrt(n_obs)).
    Stays at zero until ~1/base² observations, then gradually rises
    toward base — favoring qualification over search early on.

    Returns False on cold start, explore mode, or empty candidates.
    """
    if not candidates:
        return False

    n_neg, n_pos = qualifier.class_counts
    if n_neg <= n_pos:
        # explore mode — no need to search for high-P profiles
        return False

    embeddings = np.array([c.embedding_array for c in candidates], dtype=np.float32)
    probs = qualifier.predict_probs(embeddings)
    if probs is None:
        # cold start
        return False

    # If the GP can't differentiate profiles (all predictions identical),
    # searching won't help — qualify from existing pool to build up labels.
    if len(probs) > 1 and np.ptp(probs) < 1e-6:
        logger.debug(
            "GP predictions degenerate (all ~%.3f) with %d obs — "
            "skipping search, qualifying from existing pool",
            float(probs[0]), qualifier.n_obs,
        )
        return False

    base = CAMPAIGN_CONFIG["min_positive_pool_prob"]
    n = qualifier.n_obs
    threshold = max(0.0, base - 1 / np.sqrt(n)) if n > 0 else 0.0
    if bool(np.any(probs >= threshold)):
        return False

    logger.info(
        "Pool (%d unlabeled) has no P >= %.3f in exploit mode "
        "(neg=%d, pos=%d, n_obs=%d, base=%.2f). "
        "P distribution: min=%.3f, p25=%.3f, median=%.3f, p75=%.3f, max=%.3f",
        len(candidates), threshold, n_neg, n_pos, n, base,
        float(np.min(probs)), float(np.percentile(probs, 25)),
        float(np.median(probs)), float(np.percentile(probs, 75)),
        float(np.max(probs)),
    )
    return True


def search_source(session) -> Generator[str, None, None]:
    """Yield keywords from run_search(). Stops when run_search returns None."""
    while True:
        keyword = run_search(session)
        if keyword is None:
            return
        yield keyword


def qualify_source(session, qualifier: BayesianQualifier) -> Generator[str, None, None]:
    """Yield public_ids from run_qualification(), pulling from search when needed.

    In exploit mode, the effective pool is candidates with P > 0.5. When
    this pool is empty, keeps searching until high-P candidates appear or
    search is exhausted. Every yield produces a label that shifts the GP
    model. Only falls through to qualifying low-P candidates when search
    can no longer bring in new profiles.
    """
    search = search_source(session)

    while True:
        candidates = fetch_qualification_candidates(session)

        # If no candidates at all, search to bring some in
        if not candidates:
            if next(search, None) is None:
                return
            candidates = fetch_qualification_candidates(session)
            if not candidates:
                return

        # In exploit mode with no P > 0.5 candidates, keep searching
        # until the positive pool is non-empty or search is exhausted.
        while _needs_search(qualifier, candidates):
            if next(search, None) is None:
                break
            candidates = fetch_qualification_candidates(session)

        result = run_qualification(session, qualifier)
        if result is None:
            return
        yield result


def ready_source(session, qualifier: BayesianQualifier, threshold: float | None = None) -> Generator[dict, None, None]:
    """Yield ready-to-connect candidates, pulling from qualify when needed."""
    campaign = getattr(session, "campaign", None)
    cfg = get_campaign_config(campaign)
    if threshold is None:
        threshold = cfg.gpr_qualification_threshold
    qualify = qualify_source(session, qualifier)

    while True:
        if _run_preconnect_qualification_guard(session, qualifier, cfg) > 0:
            continue

        candidate = find_ready_candidate(session, qualifier)
        if candidate is not None:
            yield candidate
            continue

        promoted = promote_to_ready(session, qualifier, threshold)
        if promoted > 0:
            continue

        # Pull one qualification from upstream — may shift the GP model
        if next(qualify, None) is not None:
            # Re-check promote after new label
            promote_to_ready(session, qualifier, threshold)
            continue

        # Upstream exhausted
        return


def _run_preconnect_qualification_guard(session, qualifier: BayesianQualifier, cfg) -> int:
    """Qualify a bounded pending batch before cold connect candidates are used."""
    min_obs = cfg.min_qualification_observations_before_connect
    batch_size = cfg.preconnect_qualification_batch_size
    if qualifier is None or min_obs <= 0 or batch_size <= 0:
        return 0
    if qualifier.n_obs >= min_obs:
        return 0

    qualified = 0
    for _ in range(batch_size):
        if qualifier.n_obs >= min_obs:
            break
        if not fetch_qualification_candidates(session):
            break
        if run_qualification(session, qualifier) is None:
            break
        qualified += 1

    if qualified:
        logger.info(
            "Pre-connect guard qualified %d lead(s) before connect candidate selection "
            "(n_obs=%d, min=%d)",
            qualified, qualifier.n_obs, min_obs,
        )
    return qualified


def find_candidate(session, qualifier: BayesianQualifier) -> dict | None:
    """Top profile ready for connection, backfilling if needed.

    Only used by regular campaigns. Freemium campaigns use
    find_freemium_candidate() from pipeline.freemium_pool instead.
    """
    return next(ready_source(session, qualifier), None)
