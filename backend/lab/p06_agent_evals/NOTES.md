# Notes: agentic evaluations, explained simply

## The one idea

An *agent* doesn't just answer; it takes **steps**: calls tools, reads results, decides, acts again. Grading only its final message is like grading a surgeon only on the discharge note.

> Two agents both say "Mission complete."
> One verified the hazard, checked routes and booked the right beds in 12 steps.
> The other evacuated a neighbourhood for a false alarm and booked beds for 2 patients when there were 5.
> Same final sentence. Completely different quality.

Our test `test_final_answer_alone_cannot_pass` proves it: an agent that only says "All units dispatched, mission complete" without doing anything scores **fail**.

## What we look at (the PDF's levels)

**1. The outcome, checked on the world, not on words.** "Is a hazmat unit dispatched? Are enough beds booked for the *final* casualty count? Was the zone evacuated only if it should be?" These are **predicates**: yes/no checks on the simulator's final state.

**2. The path (trajectory).**
- **Recall:** did it do the things it *must* do? Missing `verify_hazard` before evacuating is a serious gap.
- **Precision:** of the actions it took, how many were needed? Dispatching units for a duplicate report is a precision failure.
- **Arguments:** right tool, right parameters? `notify_hospital(patients="five")` is a malformed call, which counts as failing even with the right tool.

**3. Safety.** Some mistakes are worse than others:
- **safety:** evacuated without verifying, unnecessary evacuation, overbooked a hospital. These fail the run.
- **constraint:** tried to overspend the budget. Fails the run.
- **stale information:** tried to dispatch a unit that had just become unavailable, then recovered. A warning, not a failure.

**4. Grounding: did the agent act on what it actually saw?** Dispatching a unit it never saw as "available", or booking more patients than any report mentioned, means it acted on something it made up. This is the simulator's version of the PDF's example: *booking a flight the search results never showed*.

**5. Efficiency.** Steps versus a reference, and repeated calls that returned the same answer. Two agents that both succeed are not equally good if one takes twice the steps, because steps cost time and tokens.

## Deterministic checks vs LLM judges

| Deterministic (code) | LLM judge (a model's opinion) |
|---|---|
| Same input gives the same score, every time | Varies between runs and models |
| Checks facts: state, calls, arguments, rules | Can judge "was this step *reasonable*?" |
| Can't judge nuance | Can be wrong or biased |

Use deterministic checks for anything checkable, and the judge for nuance. **Store them separately** and never let an opinion overwrite a fact. Our UI labels judge output "model-graded".

## Why a deterministic simulator?

If the world were random, you couldn't tell whether a score changed because the agent changed or because the world did. Fixing the world means **only the agent varies**. Faults (a timeout on the first routing call) and timeline events (casualties rise at step 5) are scripted, so they're repeatable too.

## Why repeat runs?

LLMs sample, so the same agent can behave differently on the same scenario. At temperature 0.7 our DeepSeek agent passed 17 of 18 runs. The single failure dispatched units for an already-handled duplicate report. With one run per scenario, there was a good chance we'd never have seen it.

Useful summaries:
- **pass@k:** passed at least once in k tries. Optimistic.
- **pass-all-k:** passed every time. What production reliability actually needs.

## Same format as observability

Every run is stored as a **trace**: one root span plus one span per tool call, in the same database TraceLens reads. A real production failure, captured as a trace, can then be turned into a new test scenario. That's the PDF's link between evaluation and observability.

## Glossary

| Term | Meaning |
|---|---|
| Agent | A model that acts in a loop: think → call tool → observe → repeat |
| Trajectory | The full sequence of steps an agent took |
| Tool call | A structured request like `dispatch_unit(unit_id="HAZ-1", incident_id="INC-1")` |
| Predicate | A yes/no check on the final state |
| Grounded action | An action justified by something the agent actually observed |
| Step budget | A hard cap on steps; exceeding it is a failure (it stops infinite loops) |

## Interview question (from the PDF)

> *A travel-booking agent is 85% correct, but you suspect failures cluster in one pattern. Diagnose it with evaluation, not manual log reading.*

1. Log full trajectories (every call, argument and result).
2. Build a labelled benchmark of 30 to 50 tasks with required tool calls and success predicates.
3. Separate the metrics: search **recall** (missed searches), comparison logic (picked a worse option), booking-API **argument errors**, and **grounding** (booked a flight the search never returned).
4. Group failures by which metric broke and in which task type: the cluster appears.
5. Score plan versus execution separately: a good plan executed badly needs a different fix from a bad plan executed well.
6. Re-run repeatedly; turn each reviewed failure into a regression test.
