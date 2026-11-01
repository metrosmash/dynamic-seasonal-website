# Milestone 0 spike results

- Generated: 2026-11-01T09:56:53+00:00
- Sample page: `spike_sample.html`
- Model: `gemini-3.5-flash-lite`
- Intensity: `medium`
- Runs per temperature: 1
- Temperatures: 0.5

## Results

| Temperature | Successful | Compliant | Compliance | p50 latency (s) | Max latency (s) | Mean input tokens | Mean output tokens |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.5 | 1/1 | 1/1 | 100% | 1.89 | 1.89 | 482.0 | 329.0 |

## Run details

### Temperature 0.5, run 1: completed
- Latency: 1.89s
- Input/output tokens: 482 / 329
- Format compliant: yes

Response:

    THEME: pumpkin-patch
    ACCENT: #ff7a1a
    PLACE: moon @ top-right
    PLACE: pumpkin @ before-h2:1
    PLACE: bone-divider @ before-h2:2
    PLACE: pumpkin @ before-h2:3
    PLACE: candle @ footer
    PLACE: cobweb @ top-left
    PLACE: crow @ header
    PLACE: pumpkin @ margin-left
    CSS:
    :root {
      --hw-bg: #120b08;
      --hw-text: #ebdcd0;
      --hw-link: #ff9e42;
      --hw-accent: #ff7a1a;
      --hw-surface: #1f140f;
    }
    
    body {
      background-color: var(--hw-bg);
      color: var(--hw-text);
      font-family: Georgia, serif;
    }
    
    h1, h2 {
      color: var(--hw-accent);
      border-bottom: 1px solid rgba(255, 122, 26, 0.2);
      padding-bottom: 0.3em;
    }
    
    a {
      color: var(--hw-link);
    }
    
    footer {
      background-color: var(--hw-surface);
      border-top: 2px solid var(--hw-accent);
      padding: 2rem;
      text-align: center;
    }

## Human quality review

Review the responses above against the sample page and the reference stylesheet. Record whether placements feel appropriate, CSS suggestions are useful, and whether the result would be readable.

- Visual quality notes: _pending review_
- Model/provider decision: _pending review_
- Prompt/output-format decision: _pending review_
