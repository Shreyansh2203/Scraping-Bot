name: Feature request
description: Suggest a new feature or improvement
title: "[FEATURE] "
labels: ["enhancement", "needs-triage"]
assignees: []

body:
  - type: markdown
    attributes:
      value: |
        Thanks for suggesting a feature! Please describe your idea.

  - type: textarea
    id: problem
    attributes:
      label: Problem
      description: Is your feature request related to a problem?
      placeholder: "I'm frustrated when..."
    validations:
      required: true

  - type: textarea
    id: solution
    attributes:
      label: Proposed Solution
      description: Describe the solution you'd like
      placeholder: "It would be great if the bot could..."
    validations:
      required: true

  - type: textarea
    id: alternatives
    attributes:
      label: Alternatives Considered
      description: Any alternative solutions or features you've considered

  - type: textarea
    id: context
    attributes:
      label: Additional Context
      description: Screenshots, mockups, or other context
