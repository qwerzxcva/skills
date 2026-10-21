## Description: <br>
US stocks analysis by an adversarial investment committee that combines SentiSense data, public financial sources, evidence ledgers, persona debate, and quick stock-analysis workflows while remaining read-only. <br>

This skill is ready for commercial/non-commercial use. <br>

## Publisher: <br>
[thesentitrader](https://clawhub.ai/user/thesentitrader) <br>

### License/Terms of Use: <br>
MIT-0 <br>


## Use Case: <br>
Developers and agent users use this skill to produce educational US equity analysis, quick market briefs, sourced evidence ledgers, and structured committee-style investment thesis reviews. It is intended for informational analysis and not for trading, account actions, or personalized investment advice. <br>

### Deployment Geography for Use: <br>
Global <br>

## Known Risks and Mitigations: <br>
Risk: Stock tickers and analysis queries may be sent to SentiSense when the skill uses the SentiSense API. <br>
Mitigation: Review the API data-sharing posture before installation and use only with an appropriate SentiSense API key. <br>
Risk: The skill produces educational market analysis that could be mistaken for personalized investment advice. <br>
Mitigation: Keep outputs informational, preserve the no-advice disclaimer, and avoid buy, sell, allocation, trading, or account-action instructions. <br>
Risk: Some financial, sentiment, insider, congressional, or market data may be stale, delayed, preview-limited, or unavailable. <br>
Mitigation: Require sourced evidence rows with as-of dates, disclose unavailable rows, and lower confidence when key evidence is missing or unresolved. <br>


## Reference(s): <br>
- [ClawHub skill page](https://clawhub.ai/thesentitrader/skills/us-stocks-analysis) <br>
- [SentiSense website](https://sentisense.ai) <br>
- [SentiSense API reference](https://sentisense.ai/skill.md) <br>
- [SentiSense API key page](https://app.sentisense.ai/get-api-key) <br>
- [SEC company tickers](https://www.sec.gov/files/company_tickers.json) <br>
- [SEC XBRL company concept API](https://data.sec.gov/api/xbrl/companyconcept/CIK{10digits}/us-gaap/{Concept}.json) <br>
- [FRED DGS10 CSV](https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10) <br>


## Skill Output: <br>
**Output Type(s):** [Text, Markdown, Shell commands, Configuration, Guidance] <br>
**Output Format:** [Markdown analysis briefs, evidence ledgers, committee verdicts, and inline API call examples] <br>
**Output Parameters:** [1D] <br>
**Other Properties Related to Output:** [Read-only workflow; requires SENTISENSE_API_KEY for SentiSense API calls and may use public SEC EDGAR and FRED sources when available.] <br>

## Skill Version(s): <br>
2.0.3 (source: server evidence release.version) <br>

## Ethical Considerations: <br>
Users should evaluate whether this skill is appropriate for their environment, review any generated or modified files before relying on them, and apply their organization's safety, security, and compliance requirements before deployment. <br>
