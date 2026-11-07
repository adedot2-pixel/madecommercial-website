# Questions to confirm against the real spreadsheet

Go through these with the EA, ideally with the real file open, before switching from the demo.
`python -m pipeline_followup inspect --file <path>` answers several of them automatically.

## Structure
1. Which file and sheet is the master? Are there other tabs (e.g. "Existing LPs", "Archive", one tab
   per region) that should also be read, or deliberately ignored?
2. Where does the file live (local, shared drive, OneDrive/SharePoint)? Is it synced to the laptop, and
   how quickly do edits appear?
3. Is there one row per **person** or one row per **firm**? If per firm, where are individual contacts
   kept?
4. Is there a hidden or unique ID column (a CRM ID, for example)? Contacts are currently identified by
   name + firm. Renaming either one makes the contact look new, and its snooze/done/notes history is
   lost.
5. Are there title rows, sub-headers, colour-coded rows, hidden rows or filtered views? Does colour
   carry meaning (e.g. red = urgent) that isn't written anywhere else? The tool cannot read meaning
   from colour.
6. Are rows ever deleted when a prospect dies, or moved to Dormant? (A deletion shows as "No longer in
   sheet" in the change report.)

## Field meanings
7. **Last contact date:** does it mean the last two-way contact, or the last attempt (including
   unanswered emails)?
8. **Who acted last:** is there a column for this? If it's "ball in court" or "waiting on", does it
   record whose move it is next? (If so, set `last_actor_column_means: whose_turn`.) If there's no such
   column, can it be added, or inferred from another column?
9. **Last contact type:** is a "call" on Teams or Zoom a meeting or a call for follow-up purposes? Do
   conference or dinner encounters count as meetings?
10. **Next action date:** is it a hard deadline, or a "think about it around then"? Should an explicit
    date always override the automatic rules, as it does now?
11. **Owner:** initials or full names? Should the digest be split by owner, or should colleagues get
    their own digest?
12. **Ticket size:** what does a bare number mean (millions? which currency?). Are ranges, "TBC" or
    "up to" common? Is it the potential ticket, the expected ticket, or what's already been committed?
13. **Notes:** free-form history, or only the latest update? Do they ever contain anything that must
    never be copied elsewhere? (Notes are kept out of snapshots and email bodies, and out of AI prompts
    unless enabled.)
14. **Type:** what values are used (prospect / existing / consultant / placement agent / fund of
    funds…)? Should consultants follow different rules or timings?

## Stages
15. What is the full list of stage values actually typed? `inspect` prints every value it couldn't
    match. How do they map to: Intro, Meeting held, Materials sent, Due diligence, Soft commit,
    Invested, Dormant?
16. Are there stages that don't fit, such as "Re-up", "Redemption", "Top-up" or "Waitlist"? Should
    existing investors with an active top-up conversation be followed up rather than excluded?
17. Should Dormant contacts be revived after a time (e.g. a check-in every 6 months)?

## Rules and timing
18. Are the timings right? Currently: 2 working days after a meeting; 3 working days after they reply;
    a 10-day nudge after we contact them; 30 days to "going cold".
19. Should timings vary by stage? For example, chase faster in Soft commit, or allow longer in Due
    diligence while their team works.
20. Holidays: our side uses UK bank holidays. Do clients' holidays matter too, e.g. Ramadan/Eid for
    Middle East investors, or August in Southern Europe? (These can be added as extra closures, or as a
    per-region delay.)
21. Is the first thing in the morning (e.g. 07:30 on weekdays) the right time for the digest? Who
    should receive it: the Head of EMEA, the EA, or both?

## Priority
22. Is "stage + ticket size + how overdue" the right priority mix? Should strategic names get a manual
    boost (e.g. a "Tier 1" column)?
23. Which currency should totals be shown in, and who maintains the FX rates?

## Drafts and compliance
24. What sign-off, title and disclaimer should go on emails? Are there pre-approved phrases or
    templates the firm already uses?
25. Which words or claims are off-limits in follow-ups (performance, capacity, fees, terms)? Does
    marketing or compliance need to approve the templates before use?
26. Should drafts later go straight into Outlook as **drafts** (via Microsoft Graph or a local Outlook
    add-in)? That needs IT approval for the mailbox permission. The tool would still never send.
27. AI drafting: local model only, or is the Anthropic API acceptable under the firm's policies? (The
    Claude Enterprise licence covers the claude.ai app, not API calls.) This needs a decision from IT
    and Compliance.

## Data handling
28. Where may `state.db` and the daily outputs be stored, and for how long? (Default snapshot retention
    is 120 days. Output folders are kept until deleted.)
29. Does the run log need to be kept for a set period, or sent to a central location?
