const body = document.querySelector('#body');
const counter = document.querySelector('#counter');
if (body && counter) {
  body.addEventListener('input', () => {
    counter.textContent = `${Array.from(body.value).length} / 280`;
  });
}
for (const form of document.querySelectorAll('.delete-form')) {
  form.addEventListener('submit', event => {
    if (!window.confirm('この投稿を削除しますか？')) event.preventDefault();
  });
}
for (const time of document.querySelectorAll('time[datetime]')) {
  const date = new Date(time.dateTime);
  if (!Number.isNaN(date.getTime())) {
    time.textContent = new Intl.DateTimeFormat('ja-JP', {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'}).format(date);
    time.title = date.toLocaleString('ja-JP');
  }
}
