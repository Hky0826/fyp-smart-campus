# Personal chatbot rollout

Personal lookups are disabled by default. Enable them only after the synthetic-user and access-control tests pass.

## Configuration

Set these non-secret values in the chatbot environment:

```env
RAG_PERSONALISATION_ENABLED=false
RAG_ACTIVE_SEMESTER=202607
RAG_ACTIVE_ACADEMIC_YEAR=2025/2026
RAG_CAMPUS_TIMEZONE=Asia/Kuala_Lumpur
```

The active semester and academic year are required for current courses and timetables. Profile and appointment requests remain term-independent. Invalid term or timezone values fail closed when personalisation is enabled.

## Security invariants

- Identity and roles come only from the validated JWT, active `jwt_sessions` row, and active `users` row.
- Personal queries are self-service only; identifiers in request fields or natural-language text never select an owner.
- Student timetables are reached through the authenticated student's active enrolments. Lecturer timetables are reached through the authenticated lecturer profile.
- Appointments expose only participant display name, time, duration, status, and safe location.
- Personal responses have no document citations and are stored in chatbot audit history only as `[PERSONAL_RESPONSE_REDACTED]`.
- Anonymous personal requests receive an authentication prompt without querying personal tables.

No migration is required for this MVP. Index review for `user_id`, timetable term filters, and appointment participants is a deployment follow-up after measuring production query plans.
