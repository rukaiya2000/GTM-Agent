const queryInput = document.querySelector("#paper-query");
const searchButton = document.querySelector("#search-button");
const results = document.querySelector("#results");
const status = document.querySelector("#status");

function initials(name) { return name.split(" ").filter(Boolean).slice(0, 2).map(word => word[0]).join("").toUpperCase(); }
function authorSearchUrl(name, suffix = "") { return `https://www.google.com/search?q=${encodeURIComponent(`${name} ${suffix}`.trim())}`; }

async function searchPapers() {
  const query = queryInput.value.trim();
  if (!query) { queryInput.focus(); return; }
  searchButton.disabled = true; status.className = "status"; status.textContent = "Searching the public paper index…"; results.innerHTML = "";
  try {
    const response = await fetch(`/api/papers?query=${encodeURIComponent(query)}`);
    if (!response.ok) throw new Error("Paper search is temporarily unavailable.");
    const data = await response.json();
    if (!data.length) { status.textContent = "No paper found. Try the full title, a DOI, or an arXiv ID."; return; }
    status.textContent = "Paper found. Review its authors below.";
    // The hero has done its job once there is a result; shrink it so the paper
    // and its authors fit without scrolling.
    document.body.classList.add("has-results");
    data.forEach(renderPaper);
  } catch (error) { status.className = "status error"; status.textContent = `${error.message} You can try again shortly.`; }
  finally { searchButton.disabled = false; }
}

function renderPaper(paper) {
  const card = document.querySelector("#paper-template").content.cloneNode(true);
  card.querySelector(".source-badge").textContent = (paper.source || "Public index").toUpperCase();
  card.querySelector(".paper-title").textContent = paper.title || "Untitled paper";
  card.querySelector(".paper-year").textContent = paper.year || "YEAR N/A";
  card.querySelector(".paper-meta").textContent = [
    paper.venue,
    paper.authors?.length ? `${paper.authors.length} author${paper.authors.length === 1 ? "" : "s"}` : "Authors unavailable",
    paper.citationCount != null ? `${paper.citationCount.toLocaleString()} citations` : null,
    paper.topics?.length ? paper.topics.slice(0, 2).join(", ") : null
  ].filter(Boolean).join(" · ");
  card.querySelector(".paper-abstract").textContent = paper.abstract || "No abstract was returned for this paper.";
  const paperLink = card.querySelector(".paper-link");
  paperLink.href = paper.openAccessPdf?.url || paper.url || `https://www.semanticscholar.org/search?q=${encodeURIComponent(paper.title)}`;
  const authors = card.querySelector(".authors");
  // The drawer hangs off the wrapper, not the avatar row, so it opens as a full
  // width panel under the circles instead of becoming another item in the row.
  const authorsWrap = card.querySelector(".authors-wrap");
  card.querySelector(".author-count").textContent = `${paper.authors?.length || 0} PEOPLE`;
  (paper.authors || []).forEach(author => renderAuthor(authors, authorsWrap, author, paper));
  // The abstract stays clamped to one line: you searched this paper, so the
  // authors matter more than a summary you already know.
  const abstract = card.querySelector(".paper-abstract");
  card.querySelector(".show-abstract").addEventListener("click", event => {
    const open = abstract.classList.toggle("open");
    event.currentTarget.innerHTML = open ? "Less <span>↑</span>" : "Know more <span>↓</span>";
  });
  results.append(card);
}

function renderAuthor(container, drawerHost, author, paper) {
  const fragment = document.querySelector("#author-template").content.cloneNode(true);
  const chip = fragment.querySelector(".author-chip");
  const name = author.name || "Unknown author";
  chip.querySelector(".author-avatar").textContent = initials(name);
  chip.querySelector(".author-name").textContent = name;
  // The affiliation no longer fits beside a circle, so it becomes the tooltip.
  chip.title = [name, author.affiliation, author.isCorresponding ? "Corresponding author" : null].filter(Boolean).join(" · ");
  chip.classList.toggle("corresponding", Boolean(author.isCorresponding));
  chip.addEventListener("click", () => {
    const alreadyOpen = chip.classList.contains("selected");
    container.querySelectorAll(".author-chip").forEach(other => other.classList.remove("selected"));
    drawerHost.querySelector(".research-drawer")?.remove();
    if (alreadyOpen) return;
    chip.classList.add("selected");
    openResearchDrawer(author, paper, drawerHost);
  });
  container.append(fragment);
}

function externalLink(href, text) {
  const link = document.createElement("a");
  link.href = href; link.target = "_blank"; link.rel = "noreferrer"; link.textContent = text;
  return link;
}

async function openResearchDrawer(author, paper, container) {
  const name = author.name || "Unknown author";
  container.querySelector(".research-drawer")?.remove();
  const drawer = document.querySelector("#research-template").content.cloneNode(true);
  drawer.querySelector(".drawer-name").textContent = name;
  const links = [
    ["Web search", ""], ["University / lab", "university lab"], ["Personal website", "personal website"],
    ["LinkedIn (public search)", "site:linkedin.com/in"], ["X (public search)", "site:x.com"], ["Email / contact", "email contact"]
  ];
  const linkContainer = drawer.querySelector(".search-links");
  links.forEach(([label, suffix]) => linkContainer.append(externalLink(authorSearchUrl(name, `${author.affiliation || ""} ${suffix}`.trim()), `${label} ↗`)));
  drawer.querySelector(".close-drawer").addEventListener("click", event => {
    // Clear the ring too, or a closed drawer leaves a circle looking active.
    container.querySelectorAll(".author-chip").forEach(chip => chip.classList.remove("selected"));
    event.currentTarget.closest(".research-drawer").remove();
  });
  container.append(drawer);
  const root = container.querySelector(".research-drawer");
  const facts = root.querySelector(".scholar-facts");
  const form = root.querySelector(".contact-form");
  form.addEventListener("submit", event => saveContact(event, author, paper, form));
  if (author.affiliation) form.querySelector(".contact-affiliation").value = author.affiliation;

  let profile;
  try {
    // An author ID ties the profile to this exact person; a name search does not.
    profile = author.authorId
      ? await api(`/api/authors/${encodeURIComponent(author.authorId)}`)
      : await api(`/api/author-search?name=${encodeURIComponent(name)}${author.affiliation ? `&affiliation=${encodeURIComponent(author.affiliation)}` : ""}`);
  } catch (error) {
    facts.textContent = `${error.message} The public search links below still work.`;
    return;
  }
  if (!profile?.name) { facts.textContent = "No scholarly profile matched this author. The public search links below still work."; return; }
  renderProfile(root, facts, profile, paper);
}

function renderProfile(root, facts, profile, paper) {
  const details = [
    profile.affiliations?.length ? profile.affiliations.join(" · ") : null,
    profile.paperCount != null ? `${profile.paperCount} papers` : null,
    profile.citationCount != null ? `${profile.citationCount.toLocaleString()} citations` : null,
    profile.hIndex != null ? `h-index ${profile.hIndex}` : null,
    profile.topics?.length ? profile.topics.slice(0, 3).join(", ") : null
  ].filter(Boolean);
  facts.textContent = details.length ? details.join("  /  ") : "No scholarly-profile details were returned.";
  if (profile.orcid) facts.append(" ", externalLink(profile.orcid, "ORCID ↗"));
  if (profile.homepage) facts.append(" ", externalLink(profile.homepage, "Homepage ↗"));
  if (profile.profileUrl) facts.append(" ", externalLink(profile.profileUrl, `${profile.source} ↗`));

  if (profile.matchedBy === "name") {
    const warning = root.querySelector(".match-warning");
    warning.hidden = false;
    warning.textContent = profile.ambiguous
      ? "This paper carried no author ID, so this profile was matched by name alone and other researchers share it. Verify before saving."
      : "This paper carried no author ID, so this profile was matched by name alone. Verify before saving.";
  }

  if (profile.recentPapers?.length) {
    root.querySelector(".author-work").hidden = false;
    const list = root.querySelector(".author-papers");
    profile.recentPapers.forEach(item => {
      const row = document.createElement("li");
      row.append(item.url ? externalLink(item.url, item.title || "Untitled") : document.createTextNode(item.title || "Untitled"));
      const meta = document.createElement("small");
      meta.textContent = [item.year, item.venue, item.citationCount != null ? `${item.citationCount.toLocaleString()} cites` : null].filter(Boolean).join(" · ");
      row.append(meta); list.append(row);
    });
  }

  const briefButton = root.querySelector(".make-brief");
  const briefText = root.querySelector(".author-brief");
  briefButton.addEventListener("click", async () => {
    briefButton.disabled = true; briefText.textContent = "Writing a brief from the facts above…";
    try {
      const payload = { author_id: profile.authorId, paper: paper ? { title: paper.title, year: paper.year || null } : null };
      const result = await api("/api/author-brief", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      briefText.textContent = result.brief;
    } catch (error) { briefText.textContent = error.message; }
    finally { briefButton.disabled = false; }
  });
}

async function saveContact(event, author, paper, form) {
  event.preventDefault();
  const status = form.querySelector(".save-status");
  const linkUrl = form.querySelector(".contact-link").value.trim();
  const linkLabel = form.querySelector(".contact-link-label").value;
  const payload = {
    name: author.name,
    affiliation: form.querySelector(".contact-affiliation").value.trim() || null,
    semantic_scholar_author_id: author.authorId || null,
    paper: { paper_id: paper.paperId || null, title: paper.title, year: paper.year || null, doi: paper.externalIds?.DOI || null, url: paper.openAccessPdf?.url || paper.url || null },
    links: linkUrl ? [{ label: linkLabel, url: linkUrl }] : [],
    note: form.querySelector(".contact-note").value.trim() || null
  };
  status.textContent = "Saving…";
  try {
    const response = await fetch("/api/contacts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Unable to save contact.");
    status.textContent = `Saved as contact #${data.id}.`;
    form.querySelector(".save-contact").disabled = true;
  } catch (error) { status.textContent = error.message; }
}

searchButton.addEventListener("click", searchPapers);
queryInput.addEventListener("keydown", event => { if (event.key === "Enter") searchPapers(); });
document.querySelector("[data-example]").addEventListener("click", event => { queryInput.value = event.currentTarget.dataset.example; searchPapers(); });

const workspace = document.querySelector("#workspace");
document.querySelector("#crm-button").addEventListener("click", showContacts);
document.querySelector("#queue-button").addEventListener("click", showFollowUps);

async function api(url, options) { const response = await fetch(url, options); const body = await response.json(); if (!response.ok) throw new Error(body.detail || "Something went wrong."); return body; }
function showWorkspace() { workspace.hidden = false; results.innerHTML = ""; status.textContent = ""; workspace.scrollIntoView({ behavior: "smooth", block: "start" }); }

async function showContacts() {
  showWorkspace(); workspace.innerHTML = "<h2>Your relationships</h2><div class=\"contact-list\">Loading…</div>";
  try {
    const contacts = await api("/api/contacts"); const list = workspace.querySelector(".contact-list");
    list.innerHTML = contacts.length ? "" : "No saved researchers yet. Search a paper and save an author to begin.";
    // Only a real due date gets the warning colour; a stage label is neutral.
    contacts.forEach(contact => { const row = document.createElement("article"); row.className = "contact-row"; row.innerHTML = `<button type="button">${contact.name}</button><span>${contact.affiliation || contact.relationship_stage}</span><small class="${contact.next_due ? "due" : ""}">${contact.next_due ? `Follow up ${contact.next_due}` : contact.relationship_stage}</small>`; row.querySelector("button").addEventListener("click", () => showContact(contact.id)); list.append(row); });
  } catch (error) { workspace.innerHTML = `<p class="status error">${error.message}</p>`; }
}

async function showContact(contactId) {
  showWorkspace(); workspace.innerHTML = "Loading relationship…";
  try {
    const contact = await api(`/api/contacts/${contactId}`); const view = document.querySelector("#contact-template").content.cloneNode(true);
    view.querySelector(".contact-name").textContent = contact.name; view.querySelector(".contact-affiliation").textContent = contact.affiliation || "Affiliation not yet verified";
    view.querySelector(".summary-input").value = contact.relationship_summary || ""; view.querySelector(".stage-input").value = contact.relationship_stage;
    const links = view.querySelector(".contact-links"); contact.links.forEach(link => { const a = document.createElement("a"); a.href = link.url; a.target = "_blank"; a.rel = "noreferrer"; a.textContent = `${link.label} ↗`; links.append(a); });
    const timeline = view.querySelector(".timeline"); const items = [...contact.interactions.map(item => ({ ...item, label: item.kind.replaceAll("_", " ") })), ...contact.notes.map(item => ({ ...item, occurred_at: item.created_at, label: "research note", body: item.body }))].sort((a,b) => b.occurred_at.localeCompare(a.occurred_at)); timeline.innerHTML = items.length ? "" : "No interactions yet."; items.forEach(item => { const el = document.createElement("div"); el.className = "timeline-item"; el.innerHTML = `<small>${item.label} · ${item.occurred_at.slice(0,10)}</small>${item.body}`; timeline.append(el); });
    // Wire after appending: append() empties the fragment, so handlers that query
    // it later would find nothing.
    workspace.innerHTML = ""; workspace.append(view); wireContactView(workspace, contact);
  } catch (error) { workspace.innerHTML = `<p class="status error">${error.message}</p>`; }
}

function wireContactView(view, contact) {
  view.querySelector(".back-to-contacts").addEventListener("click", showContacts);
  view.querySelector(".save-profile").addEventListener("click", async () => { await api(`/api/contacts/${contact.id}`, {method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({relationship_stage:view.querySelector(".stage-input").value,relationship_summary:view.querySelector(".summary-input").value})}); showContact(contact.id); });
  const composeButton = view.querySelector(".compose-draft");
  composeButton.addEventListener("click", async () => {
    const body = view.querySelector(".draft-body");
    const purpose = view.querySelector(".draft-purpose").value.trim() || "connect about your research";
    composeButton.disabled = true; body.value = "Drafting…";
    try {
      const result = await api(`/api/contacts/${contact.id}/generate-draft`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ channel: view.querySelector(".draft-channel").value, purpose }) });
      body.value = result.body;
    } catch (error) {
      // Falls back to a plain template so the composer is never left empty.
      const paper = contact.papers[0]?.title ? ` I enjoyed reading “${contact.papers[0].title}.”` : "";
      body.value = `Hi ${contact.name.split(" ")[0]},${paper} I’m reaching out because I’d love to ${purpose}. Would you be open to a short conversation?`;
      view.querySelector(".draft-purpose").setAttribute("title", error.message);
    } finally { composeButton.disabled = false; }
  });
  view.querySelector(".save-draft").addEventListener("click", async () => { const body=view.querySelector(".draft-body").value.trim(); if (!body) return; await api(`/api/contacts/${contact.id}/drafts`, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({channel:view.querySelector(".draft-channel").value,purpose:view.querySelector(".draft-purpose").value || "Outreach",body})}); showContact(contact.id); });
  view.querySelector(".save-interaction").addEventListener("click", async () => { const body=view.querySelector(".interaction-body").value.trim(); if (!body) return; await api(`/api/contacts/${contact.id}/interactions`, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({kind:view.querySelector(".interaction-kind").value,body,occurred_at:new Date().toISOString().slice(0,10)})}); showContact(contact.id); });
  view.querySelector(".save-followup").addEventListener("click", async () => { const reason=view.querySelector(".followup-reason").value.trim(), due_at=view.querySelector(".followup-date").value; if (!reason || !due_at) return; await api(`/api/contacts/${contact.id}/follow-ups`, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({reason,due_at})}); showContact(contact.id); });
}

async function showFollowUps() {
  showWorkspace(); workspace.innerHTML = "<h2>Follow-ups</h2><div class=\"contact-list\">Loading…</div>";
  try { const tasks = await api("/api/follow-ups"); const list=workspace.querySelector(".contact-list"); list.innerHTML=tasks.length ? "" : "No open follow-ups."; tasks.forEach(task=>{const row=document.createElement("article");row.className="contact-row";row.innerHTML=`<button type="button">${task.name}</button><span>${task.reason}</span><small class="due">${task.due_at}</small><button class="done" type="button">Done</button>`;row.querySelector("button").addEventListener("click",()=>showContact(task.contact_id));row.querySelector(".done").addEventListener("click",async()=>{await api(`/api/follow-ups/${task.id}?status=done`,{method:"PATCH"});showFollowUps();});list.append(row);}); } catch(error){workspace.innerHTML=`<p class="status error">${error.message}</p>`;}
}
