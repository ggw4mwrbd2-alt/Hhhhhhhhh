# Kalshi Tennis Scout — iPhone-friendly web app

A **read-only** Streamlit dashboard for tennis matches independently confirmed as **upcoming** and **currently listed on Kalshi**. No Kalshi account, API key, or trading permissions are needed.

## Current capabilities

- Pulls actual **open** ATP (`KXATPMATCH`) and WTA (`KXWTAMATCH`) match-winner events from Kalshi's public API.
- Requires both player outcomes to be explicitly named in Kalshi. Supports a **single YES/NO contract** (the common case) and separate-per-player YES contracts, with the corresponding side's ask price.
- Cross-checks both player names against a separate ESPN tennis *singles* fixture.
- Requires the fixture to be explicitly **pre-match** with a start time more than 10 minutes away. Does **not** trust market-open status or Kalshi close times as proof a match hasn't begun.
- Shows every qualified match within 12/24/48/72/168 hours, Arizona (MST) start time, quote, tickers and matchup.
- Reads available ESPN rankings, players' ages when the ESPN profiles provide dates of birth, limited recent results, and H2H within the loaded recent-results sample. Missing data is labeled.
- Calculates contract **cost, possible win profit, and maximum loss** before fees. Your own estimated win chance can be compared with the ask.
- Optionally uses an **OpenAI API key** for cited AI research about player form, surface and career H2H. AI will not add matches to the scanner.
- **Never places a trade.**

## iPhone deployment (no computer needed)

1. Download the ZIP file from ChatGPT onto your iPhone; open **Files**, tap ZIP to extract it.
2. In Safari, sign up/sign in to [GitHub](https://github.com/). Create a new **private** repository named `kalshi-tennis-scout` (a public repo works too if it has no secrets).
3. In that repository choose **Add file → Upload files**. Upload `streamlit_app.py`, `tennis_core.py`, `requirements.txt`, and optionally `README.md` and `.streamlit/config.toml` from the extracted folder. **Do not upload an API key**. On iPhone the GitHub mobile page may need Safari's “Request Desktop Website”.
4. Go to [Streamlit Community Cloud](https://share.streamlit.io), connect GitHub and choose **Create app**. Select that repository, branch `main`, main file `streamlit_app.py` and deploy.
5. Open the resulting `.streamlit.app` URL in Safari and use **Share → Add to Home Screen** to get an app-like icon.

No OpenAI key is needed to see the Kalshi and ESPN verification results.

### Optional AI research

In Streamlit's **Advanced settings → Secrets**, add this line, substituting a key you created in OpenAI Platform:

```toml
OPENAI_API_KEY = "YOUR_OPENAI_API_KEY"
```

Use the Platform key setup shown in ChatGPT or generate a key in your account. **Never put the key in GitHub source files or screenshots.** API model/web-search usage is billed independently of ChatGPT subscriptions. You can leave this unset and use the market scanner for free (within hosting/data-provider terms).

## Run locally (optional)

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Tests:

```bash
python -m unittest discover -s tests -v
```

## Important limitations

1. **Only verified matches are shown.** A legitimately available Kalshi match will be omitted if ESPN doesn't list it, the name match is ambiguous, the quote is unavailable, or the date/status cannot be independently verified. This is intentional and preferable to recommending an already-live event.
2. **Version 1 supports ATP and WTA singles only.** Challenger and ITF matches are omitted pending a reliable scheduled/live feed with appropriate coverage. They may still be live on Kalshi.
3. Start times can be postponed, score feeds can lag, and market quotes can move or have no available size. Refresh immediately before trading and check the live status on Kalshi itself.
4. **Prices are asks**, i.e. indicative prices to buy YES, not the last trade or midpoint. Fillable quantity and fees can alter cost. A low-priced YES contract has a high payout *if it wins*, not necessarily positive expected value.
5. H2H is **not** necessarily career H2H: it uses only the recent ESPN data loaded. Surface data and injury reports aren't guessed.
6. ESPN data is from an unofficial public endpoint. Coverage, payloads, access terms or availability may change. Kalshi APIs have rate limits and their own terms.
7. No guarantee of profitability. Market settlement can be adjusted by Kalshi rules (for example voids or exceptional outcomes).

## Data sources

- [Kalshi public market API](https://docs.kalshi.com/api-reference/market/get-markets)
- [Kalshi public events API](https://docs.kalshi.com/api-reference/events/get-events)
- ESPN tennis scoreboard `https://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard`
- [Streamlit deployment instructions](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy)

This is a personal, read-only research project. Not affiliated with ESPN or Kalshi.
