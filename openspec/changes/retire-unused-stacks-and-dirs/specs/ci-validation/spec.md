## ADDED Requirements

### Requirement: Repository layout, ignore rules and component table agree

CI SHALL fail when a top-level directory of the checked-out tree is neither tracked nor listed in the README component table, when a `.gitignore` rule matches no path in the repository's history and carries no explanatory comment, or when the README component table names a directory that does not exist.

#### Scenario: Orphan directory
- **WHEN** a tracked top-level directory is absent from the README component table
- **THEN** the check fails and names the directory

#### Scenario: Dead ignore rule
- **WHEN** a `.gitignore` rule matches nothing in history and has no `local-only` comment
- **THEN** the check fails and names the rule

#### Scenario: Consistent tree
- **WHEN** every top-level directory is tracked and documented and every ignore rule matches history or is annotated
- **THEN** the check exits zero
