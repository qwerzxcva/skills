## Description: <br>
Provides a Lance v9 format and Rust crate reference for agents working with .lance datasets, file and table formats, indexes, schema evolution, versioning, object-store configuration, and related Lance engine APIs. <br>

This skill is ready for commercial/non-commercial use. <br>

## Publisher: <br>
[tenequm](https://clawhub.ai/user/tenequm) <br>

### License/Terms of Use: <br>
Apache 2.0 <br>


## Use Case: <br>
Developers and engineers use this skill when building agents that need accurate guidance for Lance datasets, Rust crates, file and table formats, indexes, concurrency, schema evolution, performance, and object-store behavior. It helps distinguish Lance format and engine guidance from LanceDB product guidance. <br>

### Deployment Geography for Use: <br>
Global <br>

## Known Risks and Mitigations: <br>
Risk: Copy-pasted quickstart commands or examples could affect local files or datasets if run without review. <br>
Mitigation: Run examples in a disposable directory and review delete or cleanup commands before execution. <br>
Risk: Object-store examples may include non-TLS endpoints that are suitable only for local testing. <br>
Mitigation: Use TLS-enabled object-store endpoints for shared, remote, or production environments. <br>
Risk: Dataset identifiers, predicates, or operational details could be exposed through shared logs. <br>
Mitigation: Avoid sending sensitive dataset names, predicates, or identifiers to shared logging systems. <br>


## Reference(s): <br>
- [ClawHub skill page](https://clawhub.ai/tenequm/skills/lance-format) <br>
- [Publisher skill homepage](https://github.com/tenequm/skills/tree/main/skills/lance-format) <br>
- [Lance reference](artifact/references/lance-reference.md) <br>
- [Lance performance guidance](artifact/references/performance.md) <br>
- [Lance format docs mirror](artifact/references/docs/format/index.md) <br>
- [Lance quickstart docs mirror](artifact/references/docs/quickstart/index.md) <br>


## Skill Output: <br>
**Output Type(s):** [text, markdown, code, shell commands, configuration, guidance] <br>
**Output Format:** [Markdown guidance with code, command, and configuration snippets when relevant] <br>
**Output Parameters:** [1D] <br>
**Other Properties Related to Output:** [Answers should cite or use the bundled Lance reference files selected for the task.] <br>

## Skill Version(s): <br>
0.11.0 (source: frontmatter, changelog, release metadata) <br>

## Ethical Considerations: <br>
Users should evaluate whether this skill is appropriate for their environment, review any generated or modified files before relying on them, and apply their organization's safety, security, and compliance requirements before deployment. <br>
