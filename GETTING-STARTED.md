# Getting started (no coding needed)

These steps put Purchasing Research on your own computer. You do them once, in about 15 minutes. After that,
you start the app by double-clicking one file.

The app runs only on your computer. Nothing is installed on a server, and nobody else can open it.

---

## What it costs

- **The app itself is free.** You only pay Anthropic (the company behind Claude) for the searches and reading
  it does for you.
- **Each research costs a few cents with the default settings.** The app uses Claude Haiku 5.5, Anthropic's
  lowest-cost model, and "Quick" searches. After each research, the details show its estimated cost, and the
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
5. Copy the key. It starts with `sk-ant-` and is shown only once. Keep the page open until step 4 below.

Treat the key like a password. Don't email it or paste it into a chat. If a key was ever shared, delete it on
the API Keys page and create a new one.

## Step 2: Download the app (3 minutes)

1. Go to https://github.com/coreygagne/purchasing-intel and sign in to GitHub (it's a private project).
2. Click the green **Code** button, then **Download ZIP**.
3. Open your Downloads folder, right-click **purchasing-intel-main.zip** and choose **Extract All…**.
   Put it somewhere easy to find, such as your Documents folder.

## Step 3: Start the app (5 minutes the first time)

1. Open the extracted **purchasing-intel-main** folder and double-click **run.bat**.
2. If Windows shows **"Windows protected your PC"**, click **More info**, then **Run anyway**. Windows shows
   this for any downloaded program it doesn't recognize.
3. A black window opens.
   - **If it says Python is needed,** it installs it for you; choose **Yes** if Windows asks for permission.
     When it finishes, close the black window and double-click **run.bat** again.
   - **The first start then takes a minute or two** while it sets itself up.
4. Your web browser opens the app at **http://127.0.0.1:8000**. If it doesn't open by itself, type that
   address into your browser.

**Keep the black window open while you use the app.** Closing it stops the app. Next time, just double-click
**run.bat** again.

## Step 4: Paste your key (1 minute)

1. The app shows **"Connect a search provider to start"** with a box labelled **Anthropic API key**.
2. Paste the key from step 1 and click **Save**.
3. The app checks the key with Anthropic and saves it on your computer. The badge at the top right turns green:
   **Ready: Anthropic web search + AI reading**.

## Step 5: Your first research

1. Type what you need, for example `Milwaukee 2767-20` or `nitrile gloves box of 100`.
2. Leave **Quick** selected (it costs least) and click **Research**. It takes one to three minutes.
3. Read the top of the results first: the lowest comparable price, the best overall value, and why. Every
   price links to where it was found.

---

## Changing a setting

Settings live in a file named **.env** in the app folder. It's created when you save your key.

1. Close the black window to stop the app.
2. In the app folder, right-click **.env**, choose **Open with**, then **Notepad**.
3. Change the line you need, save, and double-click **run.bat** again.

| To… | Change this line |
|---|---|
| Allow more spending per month (e.g. US$25) | `PI_MONTHLY_BUDGET_USD=25` |
| Get better results at about 5x the cost | `PI_ANTHROPIC_MODEL=claude-sonnet-5-5` |
| Get the best results at about 10x the cost | `PI_ANTHROPIC_MODEL=claude-opus-5-5` |

## Cutting costs further later: a free Tavily key

Tavily is a search service with a free plan (1,000 credits a month, no card needed; about 160 standard
researches). With a Tavily key, searches no longer cost Anthropic money, and the AI reading on Haiku costs
very little.

1. Sign up at https://app.tavily.com and copy your key (it starts with `tvly-`).
2. In the app, open **Data sources**, then **Add or change API keys**, paste it in the Tavily box and click
   **Save**.

## If something goes wrong

- **The black window closes straight away:** open the folder, click the address bar, type `cmd` and press
  Enter. In the window that opens, type `run.bat` and press Enter. You'll see the message that explains
  the problem.
- **"Anthropic rejected this key":** copy the key again from the Console, or create a new one.
- **"Monthly spending limit reached":** the app's monthly limit is used up. Wait for the 1st, or raise
  `PI_MONTHLY_BUDGET_USD` (see "Changing a setting").
- **Results look thin:** try **Standard** depth. If that's still thin, switch to the Sonnet model (see
  "Changing a setting").
- **On a Mac:** the steps are the same, except you open Terminal in the app folder and run `./run.sh`
  instead of double-clicking run.bat.
