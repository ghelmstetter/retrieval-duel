# Retrieval Duel: user guide

This guide walks through the app one step at a time. For installation, see the [README](../README.md#quick-start-windows).

- [1. The top bar](#1-the-top-bar)
- [2. Basics](#2-basics)
- [3. Load](#3-load)
- [4. Profile](#4-profile)
- [5. Duel](#5-duel)
- [6. Debrief](#6-debrief)
- [7. Hosted demo vs. running it yourself](#7-hosted-demo-vs-running-it-yourself)
- [8. Settings](#8-settings)
- [Troubleshooting](#troubleshooting)

---

## 1. The top bar

The five step buttons (**Basics, Load, Profile, Duel, Debrief**) move you through the lesson. You can jump to any step once a dataset is loaded.

The badge under the title tells you what kind of answers you'll get:

| Badge | Meaning |
|---|---|
| **Live · Claude** | Your API key is set. Answers, graph building and grading are done by Claude, and cost a little. |
| **Demo mode · no API key** | No key yet. The Larkspur demo works with pre-written answers; you can't index new data. |
| **Hosted demo · pre-written answers** | The public website version. See [section 7](#7-hosted-demo-vs-running-it-yourself). |
| **Test mode · stand-in AI** | For development only: a fake AI that returns placeholder text. |

From Profile onward, a **dataset bar** under the header shows which dataset you're in, its size, and a **Change dataset** button that takes you back to Load.

---

## 2. Basics

An eight-screen walkthrough for people new to RAG: the problem, what RAG is, how vector search and GraphRAG work, communities, the tradeoffs, ways to combine them, and the demo town. Move with **Back / Next**, the progress dashes, or the arrow keys. The last button, **Build the indexes →**, takes you to Load.

---

## 3. Load

Pick a dataset, then **index** it: prepare it for searching. Indexing happens once per dataset.

### The dataset cards

| Card | What it is |
|---|---|
| **The Larkspur Gazette** (demo) | 17 short articles about a fictional harbor town, with a prebuilt graph and nine hand-made questions. Works without an API key. |
| **MultiHop-RAG** | News articles from late 2023. Its sample includes some of the dataset's own questions with official answers. |
| **GraphRAG-Bench (novel)** | One novel, split into sections, with the study's own questions. |
| **Enron emails** | A run of real emails from the public Enron corpus. |
| **+ Add your own** | Upload your own files. |

The selected card has a white outline. Clicking a public dataset or **+ Add your own** opens a panel below the cards; **Cancel**, or clicking another dataset, closes it.

### Importing a public dataset

Choose a **sample size** and click **Download sample**. The sample downloads from Hugging Face to your computer; nothing goes to Claude yet. When it's done, the dataset becomes its own card.

| Dataset | Small | Medium | Large |
|---|---|---|---|
| MultiHop-RAG | 30 articles | 60 articles | 120 articles |
| GraphRAG-Bench | about 15,000 words | about 30,000 words | about 60,000 words |
| Enron emails | 75 emails | 150 emails | 300 emails |

### Adding your own files

Give the dataset a name, choose a **passage size** (short, medium or long: how big each searchable chunk is), and choose or drop files:

- `.txt` and `.md`: one document per file
- `.pdf`: the text is extracted, one document per file
- `.json` and `.jsonl`: one document per record, taken from a `text` field (or `body` / `content`), with optional `title` and `date`

Keep it small while learning: 20 to 200 documents.

### Indexing

Before you index a new dataset, the panel shows an **estimate**: number of documents and passages, how many times Claude will read, the expected cost, and the cost per question. If the estimate is over your budget, a warning explains what will happen.

Click the pink **Index** button. A progress list shows each stage:

1. **Cut into passages**
2. **Embed passages (vector)**: on your computer, free
3. **AI reads each document (graph)**: the slow, costly part
4. **Merge duplicate names**: "Arden" and "Felix Arden" become one entity
5. **Find and summarize communities**
6. **Write test questions**

Counters show entities, relations and communities found, AI calls made (and how many came from the cache), and money spent so far. If Claude's reply for a document can't be read, that document is skipped and the final message says how many. When indexing finishes, the two panels animate the result.

For an already-indexed dataset, the button becomes **Replay indexing**, which replays the build animation without redoing any work. **Next: Profile the data →** moves on.

**Peek at the documents** shows the dataset's text. **Delete** on a card removes your own or imported datasets; click it twice to confirm.

---

## 4. Profile

A look at the shape of the data, and what it predicts:

| Card | What it tells you |
|---|---|
| **Size** | Documents, passages, entities and relations. |
| **Connectedness** | The share of entities that appear in two or more documents. High means facts are spread out, which is where graph traversal helps. |
| **Detail survival** | How many numbers, dates and amounts made it into the graph. Usually few: exact details stay with vector search. |
| **Indexing cost** | Vector vs. graph tokens, and what building the graph cost (or would cost, for the demo). |

The table below lists the dataset's test questions by type, what each one tests, and which method should win.

---

## 5. Duel

### Choosing a question

- **Question cards** are the dataset's test questions, labeled by type. Cards marked **benchmark** come from the dataset's authors, with official reference answers. Tags show **saved** (a live result is stored) and **voted**.
- Or **type your own question** and click **Ask all four**.
- The **Testing:** line says what the chosen question is designed to test. Guess the winner before the answers appear.

While the searches run, spinners and a seconds counter show progress. Live runs with four contestants usually take 15 to 40 seconds.

### The Hybrid router bar

Shows the simple Hybrid's one decision (**Vector**, **Both** or **Graph**) and why. "Decided by Claude" or "decided by simple rules" says who made the call.

### Reading the two panels

**Vector RAG (left).** Each dot is a passage; dots close together say similar things. Your question drops in as a **pink dot**, a ring grows out to the passages it picked, and each pick is labeled with its rank and similarity score (for example `#1 0.38`). The chips at the bottom show the question's key words.

**GraphRAG (right).** Each circle is a person, place or thing; each line is a relationship; shaded areas are communities. **Pink rings** mark where the search started (an entity your question named, described, or resembled). **Amber lines** light up hop by hop as the search walks outward. The most relevant facts turn **pink**, with their relationship labels. For big-picture questions, the communities light up instead: that's global search reading the community summaries.

Hover any dot, circle or community for its text.

### The four answer cards

| Card | How it searches |
|---|---|
| **Vector RAG** | The passages nearest the question. |
| **GraphRAG** | Facts gathered by walking the graph, or the community summaries for big-picture questions. |
| **Hybrid** | One routing decision, then one search. |
| **Agentic** | Rewrites the question, searches, checks whether it has enough, and searches again if not (up to three searches). |

Each card shows:

- **A grade tag** (*correct*, *partly right*, *wrong or incomplete*) when the question has a reference answer. Hover it for the judge's reason.
- **Context** (how much text the AI was given) and **latency** bars. A `~` means the time is a typical value, not a measurement.
- **Evidence it retrieved**: passages (with shared words highlighted), graph facts (with the document each came from), or summaries.

The Agentic card's **How it got there** list shows each step: **Plan** (with the rewritten question), each **Search** and what it found, each **Check** ("Not enough yet" with the next search, or "enough"), and the **Answer**. In live mode each step shows its tokens and cost, and a total appears at the end.

### Voting and the lesson

Pick the best answer: **Vector, Graph, Hybrid, Agentic, Tie** or **All wrong**. The lesson then shows your vote next to the lesson's pick, explains what happened and why, adds the auto-judge's grades and the reference answer when available, and ends with a **rule of thumb**.

### Saved results

Each live run is saved with the dataset. Picking the question again shows the saved result instantly, at no cost, with a bar saying when it ran. **Run again** asks Claude for fresh answers (it skips the reply cache, so you get a new attempt) and replaces the saved result.

The line under the results says whether answers were written live, pre-written, or need a key.

---

## 6. Debrief

A summary of your votes on this dataset: a tally of wins, and a table with each question's type, how each contestant was graded, your vote, the lesson's pick and its rule of thumb. Below it are cards on when to use each method, what to watch out for, how to test any new corpus, and ways to combine methods.

**Clear my votes** resets the votes for this dataset (saved results are kept). **Back to the duel →** returns to the questions.

---

## 7. Hosted demo vs. running it yourself

| | Hosted demo (website) | On your computer |
|---|---|---|
| Datasets | Larkspur Gazette only | Larkspur, public datasets, your own files |
| Answers | Pre-written for the nine demo questions; typed questions show evidence only | Written live by Claude |
| Agentic | Pre-written plans for demo questions (searches run live); simple rules for typed questions | Planned live by Claude |
| Votes | Kept in your browser | Kept with each dataset |
| Cost | Free | Your own Claude usage |

The hosted version never calls Claude, even if a key is configured, so visitors can't run up a bill.

---

## 8. Settings

Settings live in the `.env` file in the project folder. Restart the app after changing it.

| Setting | Default | What it does |
|---|---|---|
| `ANTHROPIC_API_KEY` | (empty) | Your key. Needed for live answers and indexing. |
| `RDUEL_WORK_MODEL` | `claude-haiku-5-5` | The cheaper model for graph building, summaries, routing, agent planning and grading. |
| `RDUEL_ANSWER_MODEL` | `claude-sonnet-5-5` | The model that writes the answers you compare. |
| `RDUEL_*_PRICE_IN / OUT` | list prices | Dollars per million tokens, used only for estimates. |
| `RDUEL_MAX_INDEX_DOLLARS` | `2.00` | Indexing stops if one run spends more than this. |
| `RDUEL_TOP_K` | `5` | How many passages vector search returns. |
| `RDUEL_GRAPH_HOPS` | `2` | How far GraphRAG walks from its starting entities. |
| `RDUEL_GRAPH_MAX_FACTS` | `30` | The most graph facts handed to the AI. |
| `RDUEL_EMBED_BACKEND` | `auto` | `fastembed` (meaning-based), `tfidf` (word matching), or `auto` (fastembed if installed). |
| `RDUEL_PORT` | `8000` | The local web address's port. |
| `HF_TOKEN` | (empty) | A Hugging Face token, only for datasets that require accepting terms. |

Everything the app stores is in the `data` folder: one folder per dataset (documents, indexes, test questions, saved results, votes) and a `cache` of Claude's replies. Deleting `data/cache` makes every AI call run fresh again; deleting a dataset's folder removes it.

---

## Troubleshooting

**The badge says "Demo mode · no API key."** Open `.env`, paste your key after `ANTHROPIC_API_KEY=`, save, and restart the app.

**The page looks unchanged after an update.** If only the page changed, refresh the browser (Ctrl+F5 for a hard refresh). If the Python code changed, close the black window and run `run.bat` again. When in doubt, restart.

**An import fails with 401 or 403.** The dataset requires accepting its terms. Accept them on huggingface.co, create a token, add `HF_TOKEN=...` to `.env`, and restart.

**An import says it couldn't reach Hugging Face.** Check your internet connection and try again; Hugging Face is occasionally busy.

**Indexing stopped at the budget.** The estimate was over `RDUEL_MAX_INDEX_DOLLARS`. Use a smaller sample or raise the budget. Rerunning reuses everything already done (cached), so you only pay for the rest.

**"Document(s) skipped" after indexing.** Claude's reply for those documents couldn't be read. The rest of the index is fine. If many are skipped, try a smaller passage size or report the error.

**Vector search only matches exact words.** fastembed isn't installed, so the app fell back to word matching (the panel header says "word matching"). Run `run.bat` again so it retries the install. The Larkspur demo uses word matching on purpose.

**The panels take a few seconds to appear.** Large graphs take a moment to lay out the first time you open them in a session; spinners show while they load. Switching back afterwards is nearly instant.

**Port 8000 is already in use.** Another program is using it. Set `RDUEL_PORT=8001` in `.env` and restart.
