# LinkedIn Outreach Copilot — Product Requirements

## Product summary

Extend Wingman into a personal outreach copilot for LinkedIn. The product helps
the user decide whom to contact, remembers the relationship context, and drafts
messages in the user's voice. The user remains responsible for every LinkedIn
action: reviewing a profile, sending a connection request, and sending a
message.

The product automates preparation and memory, not LinkedIn activity.

## Problem

Networking breaks down because relationship context is scattered across
LinkedIn, calendar events, notes, email, and memory. Before reaching out, the
user has to reconstruct who a person is, why they matter, where they met, and
what was discussed. After a conversation, follow-ups are easily forgotten.

Generic AI-written outreach is also low-value. Drafts need the context of the
relationship and the user's established writing voice.

## Goals

- Maintain a useful personal CRM for professional relationships.
- Create context-aware connection and follow-up drafts in the user's voice.
- Preserve durable relationship memory across interactions.
- Surface a small, actionable daily follow-up queue.
- Keep every LinkedIn action explicitly human-approved.

## Non-goals

- Automated LinkedIn connection requests, messages, follows, profile views, or
  engagement.
- Scraping LinkedIn at scale or attempting to bypass platform controls.
- Browser automation, auto-fill, timed clicks, randomized delays, or any
  mechanism intended to simulate human activity or evade platform detection.
- Replacing a full team CRM or sales-engagement platform.
- Autonomous outreach: no message is sent by the product.

## LinkedIn safety policy

LinkedIn does not permit third-party tools that scrape, alter, or automate
activity on its website. This product therefore must not log into LinkedIn,
read LinkedIn pages, inject into the LinkedIn UI, or perform actions on the
user's behalf. It may draft copy and open a profile URL only after the user
chooses to do so. See LinkedIn's [User Agreement](https://www.linkedin.com/legal/user-agreement)
and [prohibited-software guidance](https://www.linkedin.com/help/linkedin/answer/a1341387/prohibited-software-and-extensions?lang=en).

The product should help the user maintain a deliberate, quality-first outreach
cadence:

- Default connection-request allowance: **30 per calendar day**.
- Hard maximum recorded by the product: **35 per calendar day**. At that limit,
  the product must not present additional connection-request drafts as ready
  today; it should schedule them for a later day instead.
- Count only requests the user explicitly marks as sent. The system cannot and
  must not infer LinkedIn activity through scraping or browser monitoring.
- Do not use automated pacing, randomized waits, background browser activity,
  or other techniques intended to imitate human behavior.
- Keep outreach personalized, relevant, and easy for the user to review before
  they independently take the action on LinkedIn.

## Target user

An individual founder, operator, job seeker, investor, or GTM practitioner who
does high-value relationship building and wants better preparation and follow-up
without risking an account through automation.

## Primary user journeys

### 1. Prepare first outreach

1. User adds a person manually or imports a CSV of contacts/profile URLs.
2. User adds or confirms public profile details and the reason to reach out.
3. The copilot retrieves relevant relationship memory and accepts user-provided
   research notes.
4. It creates a concise connection note and optional follow-up sequence in the
   user's voice.
5. User edits, approves, then opens the LinkedIn profile and sends manually.
6. The user records the action and a suggested next follow-up date is saved.

### 2. Continue an existing relationship

1. User opens a contact record.
2. The copilot shows the relationship timeline: how they met, prior messages,
   meetings, notes, commitments, and last contact date.
3. It suggests an appropriate next action and drafts a message using that
   context.
4. User sends manually and records the outcome.

### 3. Daily relationship review

1. User opens a daily queue.
2. The queue ranks overdue follow-ups, promised actions, and relationships at
   risk of going cold.
3. For each contact, the user sees why now, the last interaction, and a draft.
4. User completes, snoozes, or dismisses the recommendation.

## MVP capabilities

### Contact and relationship CRM

- Create contacts manually and import contacts from CSV.
- Store name, title, company, LinkedIn URL, website, email, tags, and status.
- Track relationship stage: Prospect, Connected, Active, Nurture, or Archived.
- Record a relationship summary: how the user knows them, shared context, and
  why the relationship matters.
- Record interactions, meeting notes, commitments, and next follow-up date.

### Relationship memory

Each contact has a durable, append-only interaction timeline plus a compact
memory summary used for drafting. Memory should retain facts only when they are
grounded in a user entry, a meeting note, or an approved research source.

Memory fields:

- Profile: role, company, links, tags, and public facts.
- Relationship: how and when the user met them, shared context, relationship
  strength, and mutual connections supplied by the user.
- Interactions: messages, meetings, notes, and dates.
- Preferences: stated interests and communication preferences.
- Commitments: promised introductions, resources, or follow-ups.
- Next action: suggested action, reason, and due date.

The system must show the evidence/source for each generated summary and let the
user correct or delete memories.

### AI outreach copilot

- Draft a LinkedIn connection note from a contact, goal, and relationship
  context.
- Draft follow-up messages for a user-selected purpose.
- Offer short, natural variants rather than a long automated sequence.
- Use the existing Wingman voice corpus so drafts match the user's writing.
- Explain the context used to create a draft.
- Require an explicit user approval before a draft becomes ready to copy.

### Follow-up queue

- Generate a daily queue from due dates, commitments, and relationship stage.
- Show the suggested action, reason, last interaction, and a draft.
- Let the user complete, snooze, reschedule, or dismiss an item.
- Show the user-recorded connection-request count and remaining daily allowance.

## Data model

### Contact

`id`, `name`, `title`, `company`, `linkedin_url`, `email`, `website`, `tags`,
`relationship_stage`, `relationship_summary`, `last_contacted_at`,
`next_follow_up_at`, `created_at`, `updated_at`

### Interaction

`id`, `contact_id`, `type`, `occurred_at`, `summary`, `raw_note`, `channel`,
`outcome`, `source`, `created_at`

Interaction types: `meeting`, `message_sent`, `message_received`, `note`,
`introduction`, `reminder`, `research`.

### Memory

`id`, `contact_id`, `category`, `fact`, `source_interaction_id`, `confidence`,
`status`, `created_at`, `updated_at`

Categories: `profile`, `relationship`, `interest`, `preference`, `commitment`,
`shared_context`.

### Outreach draft

`id`, `contact_id`, `purpose`, `body`, `context_used`, `status`,
`approved_at`, `sent_at`, `created_at`

Statuses: `draft`, `ready_for_review`, `approved`, `copied`, `sent_manually`,
`discarded`.

### Follow-up task

`id`, `contact_id`, `reason`, `suggested_action`, `due_at`, `status`,
`snoozed_until`, `created_at`, `completed_at`

### Outreach activity log

`id`, `contact_id`, `action`, `occurred_at`, `user_confirmed`, `notes`

Actions include `connection_request_sent`, `message_sent`, and `message_received`.
Only a user confirmation can create a `connection_request_sent` entry.

## Technical direction

Build on Wingman's existing principles and components:

- **Voice corpus:** reuse `voice_corpus.json` for draft style conditioning.
- **Review workflow:** use an explicit draft status and human approval gate.
- **Storage:** start with Notion databases for contact review and workflow;
  retain a local SQLite store for structured relationship memory and reliable
  querying.
- **Drafting:** use a skill/LLM workflow for synthesis and writing; keep
  deterministic import, reminder, and state-transition work in Python scripts.
- **Research boundary:** accept user-provided notes and approved public sources;
  do not make LinkedIn automation a dependency.

## Acceptance criteria

- A user can import a CSV, review contacts, and create a contact record.
- A contact displays a chronological interaction timeline and editable memory
  summary.
- Given a contact, an outreach goal, and at least one contextual fact, the
  system produces a short connection-note draft in the user's voice.
- Every draft indicates the facts it used and can be edited before use.
- The product has no function that sends LinkedIn messages or requests.
- The product has no browser automation, LinkedIn scraping, auto-fill, or
  timing behavior intended to mimic a human user.
- The product counts only user-confirmed connection requests, warns at 30 per
  calendar day, and prevents further requests from being marked ready after 35.
- A daily queue shows due follow-ups and supports complete, snooze, and
  reschedule actions.
- Recording an interaction updates the contact's last-contacted date and can
  create or update the next follow-up task.

## Future opportunities

- Meeting preparation briefs based on contact memory and user-provided research.
- Email, calendar, and Slack integrations where the user authorizes them.
- Company records and relationship mapping across contacts.
- A browser-side writing overlay that assists copy/editing only after the user
  has navigated to the profile themselves.
- Personal relationship-health analytics and networking goals.
