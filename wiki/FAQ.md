# FAQ

**Does it apply to jobs for me?**
No. It finds, scores and drafts. You review and apply yourself.

**Do I need to pay for an AI API?**
No. It uses Ollama, which runs free models on your computer.

**Does it scrape LinkedIn or other sites that block bots?**
No. It uses only public APIs and feeds, respects robots.txt and never bypasses logins or CAPTCHAs.

**How does it know if a company sponsors visas?**
Only from what the job post (or an official public register) says. It saves the exact
quote and link. Hiring international staff is never treated as proof.

**Why are my citizenship and visa fields empty?**
On purpose. The system never guesses them. Fill them in under [Your Profile](Your-Profile.md).

**Is the "interview likelihood" accurate?**
It's a rough estimate based on how well your profile overlaps the job, not a prediction
from real hiring data. It's labelled that way everywhere.

**Is my data private?**
Yes. Everything stays on your computer, in your own database.

**My computer has 8 GB RAM. Will it work?**
Yes, with the small `llama3.2:3b` model. On a Mac, run Ollama natively for GPU speed.

**Can I add more countries?**
Yes. Add any two-letter country code to `preferred_countries`.

**Are the sample jobs real?**
No. They are made up for testing (all links point to example.com).
