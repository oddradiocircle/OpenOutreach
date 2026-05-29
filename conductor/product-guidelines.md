# Product Guidelines: OpenOutreach

## Tone and Voice

OpenOutreach communicates in a **friendly and approachable** style. The product lowers the barrier for founders, sales teams, and agencies who may not be deeply technical — it should feel like a knowledgeable colleague walking you through the process, not a dense engineering tool.

### Principles
- **Conversational, not clinical.** Prefer plain language over jargon. When technical terms are necessary (e.g., "Gaussian Process", "Poisson spacing"), briefly explain them or link to context.
- **Warm but efficient.** Be helpful without being verbose. Avoid unnecessary filler phrases ("Great!", "Certainly!"), but don't be terse or cold.
- **Empowering, not alarming.** Frame errors and warnings as actionable guidance, not failure messages. The user is in control.
- **Honest about what's automated.** Be transparent that actions (connecting, messaging) are AI-driven, but frame it as a smart assistant working on the operator's behalf.

## Messaging Guidelines

### LLM-Generated Outreach Messages
- Write as if the sender is a real person, not a bot. Messages should feel personally crafted.
- Never claim to have read something you haven't (e.g., "I read your latest post" unless the system actually retrieved it).
- Keep connection requests short — one or two sentences maximum.
- Follow-up messages should reference prior context from the conversation, not restart from scratch.
- Never pressure or over-sell. The tone should be curious and helpful, not pushy.

### Django Admin and UI Copy
- Labels and help text should be written for a first-time operator, not a developer.
- Use active voice: "Run campaign" not "Campaign execution initiated".
- Error messages should say what happened and what to do next: "LinkedIn session expired. Re-run the daemon to reauthenticate."

## Visual Identity

OpenOutreach is a developer tool with a clean, utilitarian aesthetic. There is no dedicated design system beyond Django Admin defaults. Keep any custom UI additions minimal and consistent with the existing admin theme.

- **No decorative elements** that don't serve a functional purpose.
- **Clarity over beauty** — information density is a feature, not a flaw.
- Prefer tables and lists over prose for structured data (leads, deals, tasks).

## Ethical Guidelines

- Never impersonate a real person or fabricate credentials in outreach messages.
- Respect LinkedIn's Terms of Service in spirit — the tool should be used for genuine outreach, not spam.
- Operators are responsible for ensuring their campaigns comply with applicable laws (GDPR, CAN-SPAM, etc.).
- The system must never send messages that are discriminatory, deceptive, or harassing.
