
###  Prompt for codex to pick issue from Github

`Implement ankit48365/trialnexa GitHub Issue #1. Read and follow AGENTS.md, create a feature branch, implement the requirements, run all prescribed quality checks, and open a pull request linked to the issue. Do not merge or publish to PyPI.`

#### UV ADD REMOVE 
uv remove "trialnexa@D:\mygit\trialnexa_codex\dist\trialnexa-0.0.0.dev1-py3-none-any.whl"

uv add "D:\mygit\trialnexa_codex\dist\trialnexa-0.0.0.dev1-py3-none-any.whl"      

#### INIT
uv run trialnexa init 

uv run trialnexa reference import --domain cdash --version 2.3 --source "cdisc_reference/cdash/imports/CDASHIG_v2.3.csv" 

#### STUDY INIT
trialnexa study list 

trialnexa study init TEGRETOL_001

trialnexa study validate TEGRETOL_001
