name: Bug report
description: Report a bug or unexpected behavior
title: "[BUG] "
labels: ["bug", "needs-triage"]
assignees: []

body:
  - type: markdown
    attributes:
      value: |
        Thanks for reporting a bug! Please fill out the form below.

  - type: input
    id: version
    attributes:
      label: Version
      description: What version of the bot are you using?
      placeholder: "0.1.0"
    validations:
      required: true

  - type: textarea
    id: description
    attributes:
      label: Bug Description
      description: A clear description of what the bug is
      placeholder: "When I send X, the bot does Y instead of Z"
    validations:
      required: true

  - type: textarea
    id: reproduction
    attributes:
      label: Steps to Reproduce
      description: Steps to reproduce the behavior
      placeholder: |
        1. Send URL '...'
        2. Bot responds with '...'
        3. Expected '...'
    validations:
      required: true

  - type: textarea
    id: logs
    attributes:
      label: Relevant Logs
      description: Paste relevant log output here
      render: shell

  - type: textarea
    id: context
    attributes:
      label: Additional Context
      description: Any other context about the problem
