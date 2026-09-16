---
name: dream
description: Stress-test a design against failure categories - concurrency, security, economics, UX, and simplification.
command: true
---

# Dream - counterfactual review

Work through a design or change hunting for the failure modes that do not show
up in the happy path.

## What this is

`claude-dream` prints a fixed checklist of failure categories. It does no
analysis and makes no model calls - its output is the same for every topic. The
analysis is yours; the script only supplies the frame. Run it if you want the
categories on screen, or work from the list below directly.

## Instructions for Claude

1. Establish the target: the topic the user named, or the current diff/context.
2. Read the relevant code. Do not reason about a design you have not looked at.
3. Work through each category, and for each one give a **concrete** failure:
   the inputs or sequence that triggers it, and what breaks.

   - **Concurrency & state**: races, lost updates, partial writes, retry storms,
     operations that are not idempotent.
   - **Security & trust**: unvalidated input, authz gaps, secrets in logs or
     errors, confused-deputy paths.
   - **Resource & failure**: unbounded growth, missing timeouts, what happens
     when a dependency is slow rather than down.
   - **Economics**: what gets expensive at 10x, and which cost is per-request.
   - **Human factors**: what a user will reasonably misread, and what an error
     message fails to tell them.
   - **Simplification**: what could be deleted entirely, and what this would look
     like with half the moving parts.

4. Skip categories that genuinely do not apply - say so in one line rather than
   inventing a finding.
5. Close with the two or three findings worth acting on, most severe first, and
   say which are speculative versus verified in the code.

Quality bar: a finding names a file and a mechanism. "Could have a race
condition" is not a finding; "two requests calling `reserve()` between the read
at line 40 and the write at line 47 both succeed" is.
