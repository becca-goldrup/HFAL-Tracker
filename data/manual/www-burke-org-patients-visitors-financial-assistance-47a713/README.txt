Hospital(s): Winifred Masterson Burke Rehabilitation Hospital
Financial assistance page: https://www.burke.org/patients-visitors/financial-assistance/
Why this folder exists: Could not open HFA page: RuntimeError: HTTP 403

Open the page above in your normal browser and save every financial assistance
document into THIS folder:
  * the application (PDF or Word file, every language posted)
  * the plain language summary
  * the full financial assistance policy
  * if the page itself has policy text, save it too: in Chrome use File > Save Page As,
    format "Webpage, HTML Only"
Keep the original file names if you can, and include the language in the name for
translations (for example "application-spanish.pdf").

Then run:   python run.py --only "Winifred Masterson Burke Rehabilitation Hospital"
The tool will note in the spreadsheet that this hospital was graded from saved files.
