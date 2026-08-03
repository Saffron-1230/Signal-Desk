const allFeed = document.querySelector('#all-feed');
const sourceArchive = document.querySelector('#source-archive');
const updated = document.querySelector('#last-updated');
const refresh = document.querySelector('#refresh');
const refreshStatus = document.querySelector('#refresh-status');
const resultCount = document.querySelector('#result-count');
const sourceResultCount = document.querySelector('#source-result-count');
const archiveSortSelect = document.querySelector('#archive-sort-select');
const archiveBrandSelect = document.querySelector('#archive-brand-select');
const archiveMonthSelect = document.querySelector('#archive-month-select');
const tabs = [...document.querySelectorAll('[role="tab"]')];

let dashboardData = null;

function prettyDate(value, withTime = false) {
  if (!value) return withTime ? 'Waiting for first refresh' : 'Date unavailable';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, withTime
    ? { dateStyle: 'medium', timeStyle: 'short' }
    : { month: 'short', day: 'numeric', year: 'numeric' }).format(date);
}

function monthLabel(value) {
  const date = new Date(value || 0);
  return Number.isNaN(date.getTime())
    ? 'Date unavailable'
    : new Intl.DateTimeFormat(undefined, { month: 'long', year: 'numeric' }).format(date);
}

function monthKey(value) {
  const date = new Date(value || 0);
  if (Number.isNaN(date.getTime())) return 'unknown';
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
}

function timestamp(value) {
  const parsed = new Date(value || 0).getTime();
  return Number.isNaN(parsed) ? 0 : parsed;
}

function articleDateValue(article) {
  return article.published_at || article.fetched_at;
}

function articleDateLabel(article) {
  const isPublished = Boolean(article.published_at && timestamp(article.published_at));
  return `${isPublished ? 'Published' : 'First seen'} ${prettyDate(articleDateValue(article))}`;
}

function escapeHtml(value = '') {
  const el = document.createElement('div');
  el.textContent = value;
  return el.innerHTML;
}

function safeUrl(value = '') {
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol)
      ? url.href.replaceAll('&', '&amp;').replaceAll('"', '&quot;')
      : '#';
  } catch {
    return '#';
  }
}

function articlesWithSources(data) {
  return Object.entries(data.sources).flatMap(([sourceId, source]) =>
    source.articles.map(article => ({
      ...article,
      sourceId,
      sourceName: source.name,
      sourceShort: source.short,
      sourceColor: source.color,
    }))
  );
}

function mainTopic(title = '') {
  const cleaned = title
    .replace(/\([^)]*\)/g, ' ')
    .split(/[:|—–]/)[0]
    .replace(/^\d+\s+/, '')
    .replace(/\s+/g, ' ')
    .trim();
  const words = cleaned.split(' ').filter(Boolean);
  return words.slice(0, 12).join(' ') || 'Marketing and search industry update';
}

function quickSummary(article) {
  const fallback = `This update from ${article.sourceName} explores ${mainTopic(article.title).toLowerCase()}. Read the full article for the complete analysis, examples, and recommendations.`;
  const text = (article.excerpt || fallback).replace(/\s+/g, ' ').trim();
  const words = text.split(' ').filter(Boolean);
  return words.length <= 100 ? text : `${words.slice(0, 100).join(' ').replace(/[.,;:!?]?$/, '')}…`;
}

function articleCard(article) {
  return `
    <article class="feed-card" style="--accent:${article.sourceColor}">
      <div class="feed-card-meta">
        <div class="update-meta"><span class="update-label">Update</span><span class="brand-chip" aria-label="Source: ${escapeHtml(article.sourceName)}"><span class="source-initials" aria-hidden="true">${escapeHtml(article.sourceShort)}</span><span class="source-full-name">${escapeHtml(article.sourceName)}</span></span></div>
        <time datetime="${escapeHtml(articleDateValue(article) || '')}">${articleDateLabel(article)}</time>
      </div>
      <h2><a href="${safeUrl(article.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(article.title)}</a></h2>
      <p class="topic-line"><strong>Main topic</strong><span>${escapeHtml(mainTopic(article.title))}</span></p>
      <div class="summary-block"><span class="summary-label">Quick summary</span><p>${escapeHtml(quickSummary(article))}</p></div>
      <a class="read-link" href="${safeUrl(article.url)}" target="_blank" rel="noopener noreferrer" aria-label="Read ${escapeHtml(article.title)} on ${escapeHtml(article.sourceName)}">Read full article <span aria-hidden="true">↗</span></a>
    </article>`;
}

function renderAllFeed() {
  if (!dashboardData) return;
  const articles = articlesWithSources(dashboardData)
    .sort((a, b) => timestamp(articleDateValue(b)) - timestamp(articleDateValue(a)));

  resultCount.textContent = `${articles.length} ${articles.length === 1 ? 'article' : 'articles'}`;
  allFeed.setAttribute('aria-busy', 'false');

  if (!articles.length) {
    allFeed.innerHTML = '<div class="empty-state"><strong>No articles found</strong><span>Choose another brand or refresh the dashboard.</span></div>';
    return;
  }

  allFeed.innerHTML = `<div class="feed-list">${articles.map(articleCard).join('')}</div>`;
}

function renderSourceArchive() {
  if (!dashboardData) return;
  const selectedBrand = archiveBrandSelect.value;
  const selectedMonth = archiveMonthSelect.value;
  const sortMode = archiveSortSelect.value;
  let articles = articlesWithSources(dashboardData);

  if (selectedBrand !== 'all') articles = articles.filter(article => article.sourceId === selectedBrand);
  if (selectedMonth !== 'all') articles = articles.filter(article => monthKey(articleDateValue(article)) === selectedMonth);

  if (sortMode === 'oldest') {
    articles.sort((a, b) => timestamp(articleDateValue(a)) - timestamp(articleDateValue(b)));
  } else if (sortMode === 'brand') {
    articles.sort((a, b) => a.sourceName.localeCompare(b.sourceName) || timestamp(articleDateValue(b)) - timestamp(articleDateValue(a)));
  } else {
    articles.sort((a, b) => timestamp(articleDateValue(b)) - timestamp(articleDateValue(a)));
  }

  sourceResultCount.textContent = `${articles.length} ${articles.length === 1 ? 'article' : 'articles'}`;
  sourceArchive.setAttribute('aria-busy', 'false');
  sourceArchive.innerHTML = articles.length
    ? `<div class="feed-list">${articles.map(articleCard).join('')}</div>`
    : '<div class="empty-state"><strong>No matching articles</strong><span>Try another brand or release month.</span></div>';
}

function populateBrands() {
  const currentValue = archiveBrandSelect.value;
  archiveBrandSelect.innerHTML = '<option value="all">All brands</option>' + Object.entries(dashboardData.sources)
    .map(([id, source]) => `<option value="${escapeHtml(id)}">${escapeHtml(source.name)}</option>`)
    .join('');
  archiveBrandSelect.value = [...archiveBrandSelect.options].some(option => option.value === currentValue) ? currentValue : 'all';
}

function populateMonths() {
  const currentValue = archiveMonthSelect.value;
  const months = [...new Map(articlesWithSources(dashboardData)
    .sort((a, b) => timestamp(articleDateValue(b)) - timestamp(articleDateValue(a)))
    .map(article => [monthKey(articleDateValue(article)), monthLabel(articleDateValue(article))])).entries()];
  archiveMonthSelect.innerHTML = '<option value="all">All months</option>' + months
    .map(([value, label]) => `<option value="${escapeHtml(value)}">${escapeHtml(label)}</option>`)
    .join('');
  archiveMonthSelect.value = [...archiveMonthSelect.options].some(option => option.value === currentValue) ? currentValue : 'all';
}

function render(data) {
  dashboardData = data;
  updated.textContent = prettyDate(data.last_updated, true);
  populateBrands();
  populateMonths();
  renderAllFeed();
  renderSourceArchive();
}

function selectView(view, focus = false) {
  tabs.forEach(tab => {
    const active = tab.dataset.view === view;
    tab.classList.toggle('is-active', active);
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
    if (active && focus) tab.focus();
  });
  document.querySelector('#panel-all').hidden = view !== 'all';
  document.querySelector('#panel-sources').hidden = view !== 'sources';
  history.replaceState(null, '', view === 'sources' ? '#sources' : '#all');
}

tabs.forEach((tab, index) => {
  tab.addEventListener('click', () => selectView(tab.dataset.view));
  tab.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    selectView(tabs[next].dataset.view, true);
  });
});

archiveSortSelect.addEventListener('change', renderSourceArchive);
archiveBrandSelect.addEventListener('change', renderSourceArchive);
archiveMonthSelect.addEventListener('change', renderSourceArchive);

async function load() {
  const dataUrl = new URL('./data/articles.json', window.location.href);
  dataUrl.searchParams.set('v', Date.now());
  const response = await fetch(dataUrl, { cache: 'no-store' });
  if (!response.ok) throw new Error('Could not load articles');
  const data = await response.json();
  render(data);
  return data;
}

refresh.addEventListener('click', async () => {
  if (refresh.disabled) return;
  refresh.disabled = true;
  refresh.classList.add('busy');
  refresh.querySelector('span:last-child').textContent = 'Refreshing…';
  refreshStatus.textContent = 'Checking for the latest published articles.';
  try {
    const data = await load();
    refreshStatus.textContent = `Dashboard refreshed. Latest published update: ${prettyDate(data.last_updated, true)}.`;
  } catch (error) {
    refreshStatus.textContent = `${error.message}. Please try again.`;
  } finally {
    refresh.disabled = false;
    refresh.classList.remove('busy');
    refresh.querySelector('span:last-child').textContent = 'Refresh';
  }
});


selectView(location.hash === '#sources' ? 'sources' : 'all');
load().catch(error => {
  allFeed.innerHTML = `<div class="loading">${escapeHtml(error.message)}</div>`;
  sourceArchive.innerHTML = `<div class="loading">${escapeHtml(error.message)}</div>`;
});

