Metro Leak Watch - the live page
=================================
A single static page that replays the leak detector on the real MetroPT-3 record.
Everything it shows was produced by the RapidMiner processes in ../process/; the page
only plays it back.

Files
-----
build_data.py      reads ../extras/results/distance_scores.csv, ../data/metropt3_windows_5min.csv,
                   ../data/failure_reports.csv and ../extras/event_metrics.json and writes
                   public/data.json. It re-computes the distance from the baseline statistics and
                   stops if it disagrees with the column RapidMiner wrote (currently: exact match).
public/index.html  the dashboard: no framework, no build step, no network calls
public/data.json   ~2.4 MB of replay data (50,527 windows)
vercel.json        static hosting config (output directory = public)

Rebuild the data
----------------
    python build_data.py

Run it locally
--------------
    cd public
    python -m http.server 8777
    open http://127.0.0.1:8777/

Opening index.html straight from the file system does not work in Chrome, because fetch()
cannot read data.json over file://. Use the tiny server above, or the deployed site.

Deploy to Vercel
----------------
From this folder (IEDC_Aaron/web):

    npx vercel login      (one time, opens the browser)
    npx vercel --prod

Answer the prompts with: set up and deploy = yes, scope = your account, link to existing
project = no, project name = metro-leak-watch, directory = ./ (vercel.json already points at
public/). The command prints the public URL when it finishes.

What the page shows
-------------------
- KPI cards: 4/4 reported leaks detected, the delay on each unseen leak, the warning before the
  company's own repair, and the false-alarm rate in the test months
- the health score (distance from February-March normal behaviour) with the alarm line, replayed
  in time, with the reported leaks shaded and the moment the alarm fired marked
- the raw sensors at the replay cursor, each with its distance from baseline in standard deviations
- a table of all four reported leaks with detection delay and hours of warning
