# Contribution statement - Group 13

Group 13, six members. Every member implemented one part of the code with its tests and reviewed
the part of another member (rotation: each member reviews the next one). Documentation, slides,
the database and the tests are not anyone's only contribution.

> Check every row before submitting and change any row that does not match what each member
> really did; fill in the review notes at the end.

## Implementation and review

| Member | Implemented (code + tests) | Reviewed |
|---|---|---|
| Marco Vito Zingrillo | Configuration and command line: `config.py`, `common.py`, `main.py`, configuration tests in `tests.py` | Antonio Natale's validation |
| Antonio Natale | CSV validation and validation report: `validation.py`, CSV validation tests in `tests.py` | Filippo Ferro's database |
| Filippo Ferro | Database schema, import without duplicates, SQL summaries: `database.py`, database tests in `tests.py` | Gabriele Grisafi's demand and policies |
| Gabriele Grisafi | Demand with NumPy and the policy classes (inheritance): `demand.py`, `policies.py`, policy tests in `tests.py` | Riccardo Capoferri's simulation |
| Riccardo Capoferri | Daily simulation, metrics and workflow: `simulation.py`, `workflow.py`, simulation tests in `tests.py` | Silvia Passaro's extension |
| Silvia Passaro | Extension B (storage) and output files: `storage.py`, `reporting.py`, storage and command-line tests in `tests.py` | Marco Vito Zingrillo's configuration |

## Other work

| Task | Members |
|---|---|
| README and design note | Marco Vito Zingrillo, Filippo Ferro |
| AI-use statement | all members |
| Slides and presentation | all members (one slide each, Marco Vito Zingrillo introduces) |
| Final check: run all commands from a fresh copy, run the tests | Antonio Natale, Riccardo Capoferri |

## Decisions taken together

* Extension B (storage constraint), checked before ordering; two allocation rules compared.
* Money stored as integer cents.
* The same demand array for every policy and scenario.
* Base policy class with the common threshold rule; subclasses only decide how much to order.
* Import rule: identical records are skipped, different records cancel the whole import.

## Review notes

| Reviewer | Part reviewed | Main comments and changes made |
|---|---|---|
| Antonio Natale | validation | _write what you checked and what was changed_ |
| Filippo Ferro | database | _..._ |
| Gabriele Grisafi | demand and policies | _..._ |
| Riccardo Capoferri | simulation | _..._ |
| Silvia Passaro | extension B | _..._ |
| Marco Vito Zingrillo | configuration | _..._ |
