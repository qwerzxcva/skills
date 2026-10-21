## Description: <br>
Trade Signal provides real-time Buy/Sell/Hold recommendations, price targets, technical analysis, and cited market research for stocks, ETFs, options strategies, and other public securities. <br>

This skill is ready for commercial/non-commercial use. <br>

## Publisher: <br>
[kslee9572](https://clawhub.ai/user/kslee9572) <br>

### License/Terms of Use: <br>


## Use Case: <br>
External users and agents use Trade Signal to request actionable stock and market analysis, including buy/sell/hold calls, entry and exit ranges, stop-loss levels, catalysts, and source-backed rationale. <br>

### Deployment Geography for Use: <br>
Global <br>

## Known Risks and Mitigations: <br>
Risk: The helper script handles query text unsafely and can run local code from a crafted query. <br>
Mitigation: Review before installing and do not run the skill on untrusted or copied query text until the script passes the query as data, for example via sys.argv or curl --data-urlencode. <br>
Risk: User queries are sent to a third-party API. <br>
Mitigation: Avoid sending confidential portfolio, account, or strategy details to the API. <br>
Risk: The skill can return actionable trading recommendations. <br>
Mitigation: Treat outputs as research support rather than personalized investment advice and require human review before trading decisions. <br>


## Reference(s): <br>
- [ClawHub Skill Page](https://clawhub.ai/kslee9572/skills/trade-signal-ttx) <br>
- [Terminal X Homepage](https://terminal-x.ai) <br>
- [Terminal X API Base](https://app.terminal-x.ai/api) <br>


## Skill Output: <br>
**Output Type(s):** [Text, Markdown, JSON, Shell commands, Guidance] <br>
**Output Format:** [JSON from the search script, with markdown-formatted analysis in response fields] <br>
**Output Parameters:** [1D] <br>
**Other Properties Related to Output:** [May include tickers, trade signals, price targets, technical indicators, related analysis, and numbered sources.] <br>

## Skill Version(s): <br>
1.0.6 (source: server release metadata; artifact frontmatter says 1.0.2) <br>

## Ethical Considerations: <br>
Users should evaluate whether this skill is appropriate for their environment, review any generated or modified files before relying on them, and apply their organization's safety, security, and compliance requirements before deployment. <br>
