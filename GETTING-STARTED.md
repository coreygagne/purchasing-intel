# Getting started (no coding needed)

These steps put Purchasing Research on your own computer. You do them once, in about 15 minutes. After that,
you start the app by double-clicking one file. Mac and Windows are both covered.

The app runs only on your computer. Nothing is installed on a server, and nobody else can open it.

---

## What it costs

- **The app itself is free.** You only pay Anthropic (the company behind Claude) for the searches and reading
  it does for you.
- **Each research costs about 10 to 15 cents with only an Anthropic key**, or about 1 cent with a free Tavily
  key added (see "Optional extra keys"). The app uses Claude Haiku 5.5, Anthropic's lowest-cost model, and
  "Quick" searches. Expensive or higher-risk items (vehicles, machinery, property, safety gear) are searched
  more deeply, which costs a little more. After each research, the details show its estimated cost, and the
  page shows your total for the month.
- **The app stops at US$10 a month by default.** When the estimated total for the month reaches US$10, it
  refuses new research until the 1st. The limit is the `PI_MONTHLY_BUDGET_USD` setting, under "Changing a
  setting" below.
- **Also set a spend limit with Anthropic** (step 1). That limit is enforced by Anthropic, so it holds even if
  the app's estimate is off.

---

## Step 1: Get an Anthropic API key (5 minutes)

1. Go to https://console.anthropic.com and sign in (or create an account).
2. **Add credit:** Anthropic's API is pay-as-you-go. Open **Billing** (in Settings) and buy a small amount of
   credit; US$5–10 is plenty to start.
3. **Set a spend limit:** in **Settings**, find **Limits** and set a monthly spend limit, for example US$10.
4. **Create the key:** open **API Keys**, choose **Create Key**, and name it "Purchasing research".
5. Copy the key. It starts with `sk-ant-` and is shown only once. Keep the page open until step 5 below.

Treat the key like a password. Don't email it or paste it into a chat. If a key was ever shared, delete it on
the API Keys page and create a new one.

## Step 2: Download the app (3 minutes)

1. Go to https://github.com/coreygagne/purchasing-intel and sign in to GitHub (it's a private project).
2. Click the green **Code** button, then **Download ZIP**.
3. Find the download in your **Downloads** folder.
   - **Mac:** Safari usually unzips it for you into a folder named **purchasing-intel-main**. If you see a
     `.zip` file instead, double-click it.
   - **Windows:** right-click **purchasing-intel-main.zip** and choose **Extract All…**.
4. Move the **purchasing-intel-main** folder somewhere easy to find, such as **Documents**.

## Step 3: Install Python (Mac, first time only, 3 minutes)

The app is written in Python, a free programming language that has to be installed once. Macs include an old
version that's too old for the app.

1. Go to https://www.python.org/downloads/macos/ and click the yellow **Download Python** button.
2. Open the downloaded file (it ends in `.pkg`) and click **Continue**, **Agree** and **Install**. Enter your
   Mac password when asked, then click **Close**.

If you skip this, the app's starter notices and opens that page for you. On **Windows**, skip this step:
`run.bat` installs Python itself.

## Step 4: Start the app (a few minutes the first time)

### On a Mac

1. Open the **purchasing-intel-main** folder and double-click **Start Purchasing Research**.
2. The first time, macOS may say it **"Not Opened"** or **"Apple could not verify…"**. macOS shows this for any
   downloaded file that isn't from the App Store. To allow it:
   - Click **Done**.
   - Open the **Apple menu**, then **System Settings**, then **Privacy & Security**.
   - Scroll down to the message about "Start Purchasing Research" and click **Open Anyway**.
   - Confirm with your password or Touch ID.
   - On older macOS versions instead: hold **Control**, click the file, choose **Open**, then **Open** again.
3. A **Terminal** window opens. The first start takes a minute or two while it sets itself up.
4. Your web browser opens the app at **http://127.0.0.1:8000**. If it doesn't open by itself, type that
   address into Safari or Chrome.

**If double-clicking doesn't work at all:**
1. Press **Command-Space**, type `Terminal` and press **Return**.
2. Type `bash` followed by a space. Don't press Return yet.
3. Drag the **Start Purchasing Research** file from Finder into the Terminal window, then press **Return**.

### On Windows

1. Open the **purchasing-intel-main** folder and double-click **run.bat**.
2. If Windows shows **"Windows protected your PC"**, click **More info**, then **Run anyway**.
3. A black window opens.
   - **If it says Python is needed,** it installs it for you; choose **Yes** if Windows asks for permission.
     When it finishes, close the black window and double-click **run.bat** again.
   - **The first start then takes a minute or two** while it sets itself up.
4. Your browser opens the app at **http://127.0.0.1:8000**.

**Keep the Terminal or black window open while you use the app.** Closing it stops the app. Next time, just
double-click the same file again.

## Step 5: Paste your key (1 minute)

1. The app shows **"Connect a search provider to start"** with a box labelled **Anthropic API key**.
2. Paste the key from step 1 and click **Save**.
3. The app checks the key with Anthropic and saves it on your computer. The badge at the top right turns green:
   **Ready: Anthropic web search + AI reading**.

## Step 6: Your first research

1. Type what you need, for example `Milwaukee 2767-20` or `nitrile gloves box of 100`.
2. Leave **Quick** selected (it costs least) and click **Research**.
3. The app may ask up to four short questions, such as how much you need or whether used is OK. Answer the
   ones you know and leave the rest blank; it says what it assumed for those. It remembers your answers for
   that item. Click **Research** again. It takes one to three minutes.
4. Read the top of the results first: the recommended option and why, the lowest comparable price, the best
   overall value, and the options side by side. Every price links to where it was found.
5. Open the **Suppliers & quotes** tab for Thunder Bay suppliers first, with their phone numbers and emails
   (each shows where it was found). For suppliers that don't publish a price, **Open in email** starts a
   ready-made quote request in your email program; nothing is sent until you send it.
6. The **Coverage** tab shows what was searched and what couldn't be reached.

Not sure exactly what you need? Type a broad term such as `radios`, `work lights`, `air compressors` or
`safety glasses`. The app shows the main types and what each is for; click one to search for it. Its
checklist (labelled general guidance) goes into your quote requests.

Have the item in front of you, or a picture of it on screen? Click **Photo** (next to Research) and choose a
photo, or just copy a picture (right-click > Copy Image, or a screenshot) and press Cmd+V on the page. If you've
typed something first ("hi-rail pickup"), the photo adds detail to it instead of replacing it. A photo ideally
shows the label or nameplate. The app reads what it can and suggests a search; check it, edit it if needed, then click
**Research this**. Reading a photo uses the Anthropic key and costs a fraction of a cent to a few cents. **Try Google
Lens** opens Lens if you'd rather search visually.

Next to Quick / Standard / Deep, **In Thunder Bay** and **Outside Thunder Bay** choose where to look. Both are on
by default; turn one off to search only in town or only outside it.

**Filters** (next to Quantity) sets a price range with a slider, and for vehicles and equipment a year range,
maximum km and maximum hours. On a result, change them and click **Apply to this result**: no new search, no
cost. Listings that don't state the year, km or hours stay in and say "not stated".

Links with a small frame mark show the listing's picture when you point at them, so you don't have to open each
one (on a computer; phones have no hover).

To tidy the home page, **Clear list** next to Recent searches clears that list (saved comparisons are kept).

For vehicles, equipment, property and used items, the app doesn't pick a "best price": it lists the listing
pages and local dealers for you to compare, because condition and options matter more than the asking price.

---

## Changing a setting

Settings live in a file named **.env** in the app folder. It's created when you save your key.

1. Close the Terminal or black window to stop the app.
2. Open the settings file:
   - **Mac:** open the app folder in Finder, then hold **Command (⌘)** and **Shift (⇧)** and press the
     **full-stop key (.)**, next to the comma. Hidden files appear greyed out; press the same keys to hide
     them again.
     Then right-click **.env** and choose **Open With**, then **TextEdit**.
   - **Windows:** right-click **.env**, choose **Open with**, then **Notepad**.
3. Change the line you need, save, and start the app again.

| To… | Change this line |
|---|---|
| Allow more spending per month (e.g. US$25) | `PI_MONTHLY_BUDGET_USD=25` |
| Get better results at about 5x the cost | `PI_ANTHROPIC_MODEL=claude-sonnet-5-5` |
| Get the best results at about 10x the cost | `PI_ANTHROPIC_MODEL=claude-opus-5-5` |

## Optional extra keys (both have free plans)

- **Tavily** makes searching cost almost nothing: its free plan gives 1,000 credits a month (about 90 Quick
  researches; a Quick research uses 8 to 11). Sign up at https://app.tavily.com and copy the key; it starts
  with `tvly-`.
- **SerpApi** adds Google Shopping (Canada) prices from real stores and Google Maps listings of Thunder Bay
  businesses: its free plan gives 250 searches a month, and a Quick research uses two. Sign up at
  https://serpapi.com and copy the key from https://serpapi.com/manage-api-key.

To add either one: in the app, open **Data sources**, then **Add or change API keys**, paste it in the
right box and click **Save**. The badge at the top right then lists it, for example
**Ready: Tavily + Google Shopping + AI reading**.

## Updating to a new version

Your keys and saved research stay where they are. The app updates itself from the file you download.

1. Close the Terminal (or black) window to stop the app.
2. Go to https://github.com/coreygagne/purchasing-intel and click **Code**, then **Download ZIP**. Leave the
   file in your **Downloads** folder. You don't need to unzip or move it.
3. Start the app the usual way: double-click **Start Purchasing Research** on a Mac, or **run.bat** on
   Windows, in the folder you already use.
4. The window says "A newer version was downloaded" and asks "Update this copy now?". Press **Return**.
   It copies the new version over the old one, keeps your keys, saved research and settings, and restarts.
   If you type **n**, it starts the version you have and won't ask again about that download.
5. Afterwards you can delete the downloaded file from Downloads.

**If your copy is older than October 22, 2026**, it doesn't have the updater yet. Update it once the old way:
1. Rename your folder to **purchasing-intel-old**.
2. Download and unzip the new version next to it.
3. Start the new copy. It brings your keys and saved research across.

From then on, updating is just steps 1 to 4 above. On Windows, the old way also means copying the **.env** file
and the **data** folder into the new folder yourself.

## If something goes wrong

- **Mac: "could not be executed because you do not have appropriate access privileges":** use the Terminal
  method under "If double-clicking doesn't work at all" in step 4.
- **"Address already in use":** the app is already running in another window. Use that window's app, or close
  that window first.
- **Windows: the black window closes straight away:**
  1. Open the folder, click the address bar, type `cmd` and press Enter.
  2. In the window that opens, type `run.bat` and press Enter. You'll see the message that explains the
     problem.
- **"Anthropic rejected this key":** copy the key again from the Console, or create a new one.
- **"Monthly spending limit reached":** the app's monthly limit is used up. Wait for the 1st, or raise
  `PI_MONTHLY_BUDGET_USD` (see "Changing a setting").
- **Results look thin:** try **Standard** depth. If that's still thin, switch to the Sonnet model (see
  "Changing a setting").
- **A price looks far too low:** open the listing. It's often a different size, a per-foot price or a
  page that lists several sizes. The app sets such prices aside from its recommendations and says why, but
  always check the size on the page before ordering.
