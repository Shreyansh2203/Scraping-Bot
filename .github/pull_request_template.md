name: Pull request
description: Create a pull request
title: "[PREFIX] "
labels: []
assignees: []

body:
  - type: markdown
    attributes:
      value: |
        Thanks for contributing! Please fill out this PR template.

  - type: input
    id: prefix
    attributes:
      label: PR Prefix
      description: Choose a prefix for your PR title
      placeholder: "feat | fix | docs | refactor | test | chore"
      options:
        - feat
        - fix
        - docs
        - refactor
        - test
        - chore
    validations:
      required: true

  - type: textarea
    id: description
    attributes:
      label: Description
      description: Describe your changes
      placeholder: "This PR adds..."
    validations:
      required: true

  - type: textarea
    id: related
    attributes:
      label: Related Issues
      description: Link to related issues (Closes #123)

  - type: textarea
    id: checklist
    attributes:
      label: Checklist
      description: Confirm all items are checked
      value: |
        - [ ] I have run `ruff check .` and `black --check .`
        - [ ] I have run `mypy --strict bot/ core/`
        - [ ] I have run `pytest` and all tests pass
        - [ ] I have updated the documentation if needed
        - [ ] My changes generate no new warnings
