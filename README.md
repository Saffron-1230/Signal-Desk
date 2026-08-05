# Signal Desk

Signal Desk is Saffron Edge's free, public marketing and SEO news dashboard. It collects and archives articles from Ahrefs, Search Engine Land, Search Engine Journal, Semrush, Factors.ai, WebFX, Google Ads, Google Developers, and the main Google Blog.

## Live website

After GitHub Pages is enabled, the dashboard is published at:

https://saffron-1230.github.io/Signal-Desk/

## Automatic updates

The GitHub Actions workflow refreshes the dashboard every day at 10:00 AM and 6:00 PM Asia/Kolkata time. It fetches each source independently, retries failures once, updates the saved SQLite history, exports the complete stored archive as browser-ready JSON, and republishes the website.

The dashboard's **Run update** button opens the secure GitHub workflow control. To run an unscheduled collection, choose **Run workflow** on the `main` branch. When you return to the dashboard, it checks the published data again automatically.

## Free-hosting design

- GitHub Pages serves the static HTML, CSS, JavaScript, and exported article data.
- GitHub Actions runs the Python collector on the schedule and for manual requests.
- SQLite retains deduplicated article history inside the repository.
- No API keys, paid feeds, server, or always-on computer are required.

Because GitHub Pages on a free GitHub account requires a public repository, the code and collected public article metadata are visible to everyone. No passwords or private Windows files are included.

## Run locally

Create a Python environment, install the dependencies, and export the current dashboard data:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python export_static.py
python -m http.server 8000 --directory site
```

Open http://localhost:8000. To collect new articles before opening it, run `python export_static.py --refresh`.
