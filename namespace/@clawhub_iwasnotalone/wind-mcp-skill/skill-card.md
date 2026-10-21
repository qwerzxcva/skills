## Description: <br>
Routes agent requests to Wind financial data services for supported equity, fund, index, bond, announcement, news, macroeconomic, and industry data queries. <br>

This skill is ready for commercial/non-commercial use. <br>

## Publisher: <br>
[iwasnotalone](https://clawhub.ai/user/iwasnotalone) <br>

### License/Terms of Use: <br>
MIT-0 <br>


## Use Case: <br>
External users and financial-data agents use this skill to answer supported market data, company document, news, and macroeconomic queries through Wind data services. The skill guides routing, parameter construction, credential setup, and error handling for Wind-backed financial data calls. <br>

### Deployment Geography for Use: <br>
Global <br>

## Known Risks and Mitigations: <br>
Risk: The skill executes local Node.js code and contacts Wind endpoints. <br>
Mitigation: Review the skill before installation and run it only in environments where local script execution and outbound Wind service access are approved. <br>
Risk: The skill can store a Wind API key in user-global or skill-local configuration. <br>
Mitigation: Use scoped keys, keep generated config files out of source control, rely on restrictive file permissions, and rotate keys if exposure is suspected. <br>
Risk: The skill may update itself in the background during use. <br>
Mitigation: Disable or remove the updater when strict change control is required, and verify the installed version or file hashes before use. <br>


## Reference(s): <br>
- [Wind AI Financial Market](https://aifinmarket.wind.com.cn) <br>
- [ClawHub Skill Page](https://clawhub.ai/iwasnotalone/skills/wind-mcp-skill) <br>
- [Tool Contracts](references/tool-contracts.md) <br>
- [Indicators](references/indicators.md) <br>
- [Tool Manifest](references/tool-manifest.json) <br>
- [Tool Validation Rules](references/tool-validation-rules.json) <br>
- [Error Codes](references/error-codes.json) <br>


## Skill Output: <br>
**Output Type(s):** [text, markdown, shell commands, configuration, guidance] <br>
**Output Format:** [Markdown or text responses with inline shell commands and JSON parameters] <br>
**Output Parameters:** [1D] <br>
**Other Properties Related to Output:** [May include JSON-formatted Wind MCP results and structured error guidance; user-facing answers should be based only on Wind-returned data.] <br>

## Skill Version(s): <br>
1.0.0 (source: server release evidence) <br>

## Ethical Considerations: <br>
Users should evaluate whether this skill is appropriate for their environment, review any generated or modified files before relying on them, and apply their organization's safety, security, and compliance requirements before deployment. <br>
