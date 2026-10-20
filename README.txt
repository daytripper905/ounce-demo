OUNCE DEMO - AUTOMATIC BUILD KIT
================================
What this is: the demo version of An Ounce of Prevention plus a robot (GitHub Actions) that builds the
Windows download and publishes it. After setup you only touch it when you release a new version.

WHAT'S IN HERE
  app.py                    the DEMO program (30 days, 10 own assets, DEMO mark, sample data preloaded)
  build_bundle.ps1          builds the portable Windows folder + zip (has new -Demo and -PublicKey switches)
  ci_smoke.py               automatic test the robot runs before publishing
  Sample CSV files/         copied into the download
  .github/workflows/        the robot's instructions
  (BlackMarble_2016_3km.jpg and world.jpg: add them next to app.py if you want the images in the demo; optional)

ONE-TIME SETUP (about 15 minutes)
1. Make a free account at github.com (use a business email such as support@bioship.ca if you like).
2. New repository. Name: ounce-demo. Choose PUBLIC. (Release downloads from a private repository
   need a login, so nobody could download. The demo code is plain text inside any download anyway,
   so a public repository gives nothing away. License codes are still unforgeable.)
3. In the new repository: Add file > Upload files. Drag in EVERYTHING from this kit, including the
   .github folder. Commit.
4. Get your PUBLIC key (the public half is safe to publish; never use the private one here):
   in your dev folder run   python make_license.py stamp --app some_copy_of_app.py
   and copy the 64-character "Public key:" line it prints.
5. In the repository: Settings > Secrets and variables > Actions > Variables tab > New repository variable.
   Name: OUNCE_PUBLIC_KEY      Value: the 64 characters.
6. Actions tab > "Build and publish the demo" > Run workflow > tag: demo-v1.0.2 > Run.
   Wait 15-25 minutes. Green tick = published. Red cross = open it and send me a screenshot.
7. Your permanent download link is:
   https://github.com/<your-github-name>/ounce-demo/releases/latest/download/An-Ounce-of-Prevention-Demo.zip
   Tell me <your-github-name> and I put it on the website's Download buttons.

LATER, FOR A NEW VERSION: replace app.py in the repository, then run the workflow again with a new tag
(demo-v1.0.3). The link above never changes.

KNOWN LIMITS (be aware, none are urgent)
- Honour system: someone could delete the database file for a fresh 30 days, or edit app.py. They can never create
  a license code.
- The build is not code-signed, so Windows shows "Windows protected your PC" (More info > Run anyway). The READ ME
  tells people. Code-signing certificate later, once it's earning money.
