## Description: <br>
Neural Memory provides an associative persistent memory layer for storing, recalling, and auto-capturing agent context across sessions. <br>

This skill is ready for commercial/non-commercial use. <br>

## Publisher: <br>
[nhadaututtheky](https://clawhub.ai/user/nhadaututtheky) <br>

### License/Terms of Use: <br>
MIT-0 <br>


## Use Case: <br>
Developers and agent users use this skill to add local persistent memory to agent workflows, retrieve relevant past context, and capture decisions, errors, preferences, and TODOs for future recall. <br>

### Deployment Geography for Use: <br>
Global <br>

## Known Risks and Mitigations: <br>
Risk: Automatic capture and reuse of conversation-derived memories can persist sensitive or unintended context across agent runs. <br>
Mitigation: Before enabling autoContext or autoCapture, decide which conversations may be saved and establish a process to inspect or delete saved memories. <br>
Risk: A shared brain can mix context across projects or users. <br>
Mitigation: Use separate brain names for different projects or users and verify NEURALMEMORY_BRAIN before running the skill. <br>
Risk: Optional embedding providers could send memory content outside the local machine. <br>
Mitigation: Keep local operation unless an external embedding provider is explicitly approved for the data being stored. <br>


## Reference(s): <br>
- [ClawHub Skill Page](https://clawhub.ai/nhadaututtheky/skills/neural-memory) <br>
- [ClawHub Publisher Profile](https://clawhub.ai/user/nhadaututtheky) <br>


## Skill Output: <br>
**Output Type(s):** [Text, Markdown, Shell commands, Configuration, Guidance] <br>
**Output Format:** [Markdown guidance with shell command examples and JSON configuration snippets] <br>
**Output Parameters:** [1D] <br>
**Other Properties Related to Output:** [Includes install commands, OpenClaw plugin configuration, MCP configuration, and memory-tool usage examples.] <br>

## Skill Version(s): <br>
4.59.1 (source: server release evidence) <br>

## Ethical Considerations: <br>
Users should evaluate whether this skill is appropriate for their environment, review any generated or modified files before relying on them, and apply their organization's safety, security, and compliance requirements before deployment. <br>
