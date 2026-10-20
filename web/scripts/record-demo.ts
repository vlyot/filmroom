/**
 * Records the demo video: a scripted walk through the live app, with caption cards and a visible cursor added
 * to the recording only (the app itself is untouched). Writes ../demo/filmroom-demo.webm and fails if the
 * video runs past the time limit.
 *
 * Usage (from web/): npm run record:demo   [DEMO_URL=... to record another deployment]
 */
import { mkdir, rm } from "node:fs/promises"
import { chromium, type Locator, type Page } from "playwright"

const SITE = process.env.DEMO_URL ?? "https://vlyot.github.io/filmroom/"
const REPO = "https://github.com/vlyot/filmroom#how-it-works"
const MATCH = "2019_09_09_001"
const FLAG_AT = "02:53"
const QUESTION =
  "Show me possessions we lost in midfield after a switch of play."
const OUT_DIR = "../demo"
const OUT = `${OUT_DIR}/filmroom-demo.webm`
const LIMIT_S = 115
const SIZE = { width: 1920, height: 1080 }

const pause = (ms: number) => new Promise((r) => setTimeout(r, ms))

/** Adds the caption card, title card and cursor to the current document (again after a full navigation). */
async function decorate(page: Page) {
  await page.evaluate(() => {
    if (document.getElementById("demo-caption")) return
    const style = document.createElement("style")
    style.textContent = `
      #demo-caption { position: fixed; left: 50%; bottom: 48px; transform: translateX(-50%); z-index: 9999;
        max-width: 1400px; padding: 18px 32px; border-radius: 16px; background: rgba(12, 14, 20, 0.88);
        color: #fff; font: 600 30px/1.35 "Plus Jakarta Sans Variable", "Plus Jakarta Sans", sans-serif;
        text-align: center; box-shadow: 0 12px 40px rgba(0,0,0,.35); transition: opacity .35s; opacity: 0;
        pointer-events: none; }
      #demo-title { position: fixed; inset: 0; z-index: 10000; display: flex; flex-direction: column;
        align-items: center; justify-content: center; gap: 20px; background: #0c0e14; color: #fff;
        font-family: "Plus Jakarta Sans Variable", "Plus Jakarta Sans", sans-serif; transition: opacity .6s; }
      #demo-title h1 { font-size: 96px; font-weight: 700; margin: 0; letter-spacing: -0.02em; }
      #demo-title p { font-size: 36px; margin: 0; opacity: .75; }
      #demo-cursor { position: fixed; z-index: 10001; width: 22px; height: 22px; margin: -11px 0 0 -11px;
        border-radius: 50%; background: rgba(255, 196, 0, .9); border: 3px solid #fff;
        box-shadow: 0 2px 10px rgba(0,0,0,.4); pointer-events: none; left: 960px; top: 540px;
        transition: left .5s ease-in-out, top .5s ease-in-out, transform .15s; }`
    document.head.append(style)
    for (const id of ["demo-caption", "demo-cursor"]) {
      const el = document.createElement("div")
      el.id = id
      document.body.append(el)
    }
  })
}

async function caption(page: Page, text: string | null) {
  await page.evaluate((text) => {
    const el = document.getElementById("demo-caption")!
    el.style.opacity = text ? "1" : "0"
    if (text) el.textContent = text
  }, text)
}

async function titleCard(page: Page, title: string, line: string, ms: number) {
  await page.evaluate(
    ([title, line]) => {
      const el = document.createElement("div")
      el.id = "demo-title"
      el.innerHTML = `<h1></h1><p></p>`
      el.querySelector("h1")!.textContent = title
      el.querySelector("p")!.textContent = line
      document.body.append(el)
    },
    [title, line]
  )
  await pause(ms)
  await page.evaluate(() => {
    const el = document.getElementById("demo-title")!
    el.style.opacity = "0"
    setTimeout(() => el.remove(), 600)
  })
  await pause(600)
}

/** Moves the visible cursor onto the element, then clicks it. */
async function click(page: Page, target: Locator) {
  await target.scrollIntoViewIfNeeded()
  const box = (await target.boundingBox())!
  const x = box.x + box.width / 2
  const y = box.y + box.height / 2
  await page.evaluate(
    ([x, y]) => {
      const el = document.getElementById("demo-cursor")!
      el.style.left = `${x}px`
      el.style.top = `${y}px`
    },
    [x, y]
  )
  await pause(550)
  await page.evaluate(() => {
    const el = document.getElementById("demo-cursor")!
    el.style.transform = "scale(.7)"
    setTimeout(() => (el.style.transform = ""), 150)
  })
  await target.click()
}

async function choose(page: Page, select: string, option: string) {
  await click(page, page.getByRole("combobox", { name: select }))
  await pause(400)
  await click(page, page.getByRole("option", { name: option, exact: true }))
}

async function scrollTo(page: Page, target: Locator) {
  await target.evaluate((el) =>
    el.scrollIntoView({ behavior: "smooth", block: "center" })
  )
  await pause(900)
}

async function record() {
  await rm(OUT_DIR, { recursive: true, force: true })
  await mkdir(OUT_DIR, { recursive: true })
  const browser = await chromium.launch()
  const context = await browser.newContext({
    viewport: SIZE,
    recordVideo: { dir: OUT_DIR, size: SIZE },
    colorScheme: "light",
  })
  const page = await context.newPage()
  const started = Date.now()

  // 1. The problem (the title card is drawn on a blank page, so the video doesn't open on a white load)
  await page.setContent("<html style='background:#0c0e14'></html>")
  await decorate(page)
  await titleCard(page, "FilmRoom", "What was on, and not taken", 3500)
  await page.goto(SITE)
  await page
    .getByRole("button", { name: /Data source: Live/ })
    .waitFor({ timeout: 30_000 })
  await decorate(page)
  await caption(
    page,
    "Analysts spend hours finding the moments where a better option was on."
  )
  await choose(page, "Tactical style", "Possession + High Press")
  await pause(2500)

  // 2. A live flag
  await caption(
    page,
    "Replay a match: each possession is analysed the moment it ends."
  )
  await click(page, page.locator(`a[href="#/m/${MATCH}"]`))
  await click(page, page.getByRole("radio", { name: "10×" }))
  await click(page, page.getByRole("button", { name: "Play" }))
  await page
    .getByLabel(/^Flagged moment at/)
    .first()
    .waitFor({ timeout: 30_000 })
  await caption(
    page,
    "Each flag is a moment where a clearly better option was on."
  )
  const flag = page.getByLabel(`Flagged moment at ${FLAG_AT}`)
  await flag.waitFor({ timeout: 40_000 })
  await pause(1500)
  await click(page, page.getByRole("button", { name: "Pause" }))

  // 3. The breakdown
  await click(page, flag)
  await page.getByText("What was on").first().waitFor()
  await caption(
    page,
    "The breakdown: what was on, each option's odds and threat, ranked under the coach's style."
  )
  await pause(6000)
  await caption(
    page,
    "Mistral explains it. Code fills every number and name; a verifier rejects anything else."
  )
  await pause(6000)

  // 4. The style switch
  await caption(
    page,
    "Change the coach's style and the verdict changes, with the principle that flipped it."
  )
  await choose(page, "Tactical style", "Counter + Low Block")
  await scrollTo(page, page.getByText("Verdict changed").first())
  await pause(6000)

  // 5. Audiences and languages
  await caption(
    page,
    "The same moment for coach, player or fan, in English or Spanish."
  )
  await click(page, page.getByRole("radio", { name: "Fan" }))
  await pause(2000)
  await choose(page, "Narrative language", "Spanish")
  await pause(4500)
  await choose(page, "Narrative language", "English")

  // 6. The analyst agent
  await caption(
    page,
    "Ask the analyst: an Agent Framework agent calling the engine's tools over MCP."
  )
  await click(page, page.getByRole("button", { name: "Ask the analyst" }))
  await page.getByLabel("Question").fill(QUESTION)
  await pause(1200)
  await click(page, page.getByRole("button", { name: "Send" }))
  await pause(12_000)

  // 7. Architecture
  await page.goto(REPO)
  await decorate(page)
  await caption(
    page,
    "The engine computes; the LLM explains. Agent Framework, MCP, GitHub Actions, Pages and Railway."
  )
  await pause(1500)
  await page.mouse.wheel(0, 200)
  await pause(7000)
  await titleCard(page, "FilmRoom", "vlyot.github.io/filmroom", 3500)

  const seconds = (Date.now() - started) / 1000
  const video = page.video()!
  await context.close()
  await video.saveAs(OUT)
  await video.delete()
  await browser.close()
  console.log(`wrote ${OUT} (${seconds.toFixed(0)} s)`)
  if (seconds > LIMIT_S) {
    console.error(`longer than ${LIMIT_S} s; tighten the pauses`)
    process.exitCode = 1
  }
}

await record()
