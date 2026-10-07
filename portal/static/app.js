'use strict';
document.querySelectorAll('[data-filter]').forEach(input => input.addEventListener('input', () => {
  document.querySelectorAll('#' + input.dataset.filter + ' tbody tr').forEach(row => {
    row.hidden = !row.textContent.toLowerCase().includes(input.value.toLowerCase());
  });
}));
const picker = document.getElementById('upload-files');
if (picker) picker.addEventListener('change', () => {
  const files = Array.from(picker.files);
  document.getElementById('file-summary').textContent = files.length.toLocaleString('fa') + ' فایل · ' + (files.reduce((s,f) => s+f.size, 0)/1048576).toLocaleString('fa',{maximumFractionDigits:1}) + ' مگابایت';
});
const upload = document.getElementById('upload-form');
if (upload) upload.addEventListener('submit', event => {
  event.preventDefault();
  const button = upload.querySelector('button'), progress = document.getElementById('upload-progress'), error = document.getElementById('upload-error');
  button.disabled = true; progress.hidden = false; error.hidden = true;
  const request = new XMLHttpRequest(); request.open('POST', upload.action); request.setRequestHeader('Accept','application/json');
  request.upload.onprogress = e => { if (e.lengthComputable) progress.value = 100*e.loaded/e.total; };
  const fail = message => { button.disabled = false; error.textContent = message; error.hidden = false; };
  request.onload = () => {
    let body; try { body = JSON.parse(request.responseText); } catch (_) { fail('پاسخ سرور نامعتبر است؛ دوباره تلاش کنید.'); return; }
    if (request.status===202) location.assign('/portal/jobs/'+encodeURIComponent(body.job_id));
    else fail(body.detail || 'بارگذاری انجام نشد.');
  };
  request.onerror = () => fail('اتصال قطع شد؛ وضعیت آپلود را بررسی کنید.');
  request.send(new FormData(upload));
});
const job = document.querySelector('[data-job]');
if (job && ['queued','processing'].includes(job.dataset.jobStatus)) {
  const poll = async () => {
    try {
      const response = await fetch('/api/jobs/'+encodeURIComponent(job.dataset.job), {cache:'no-store'});
      if (response.status===401) { location.assign('/portal/login'); return; }
      if (!response.ok) throw new Error('status');
      const data = await response.json();
      document.getElementById('job-label').textContent = data.label;
      document.getElementById('job-count').textContent = data.processed+' / '+data.total+' تصویر';
      const bar = document.getElementById('job-progress'); bar.max = data.total || 1; bar.value = data.processed;
      if (!['queued','processing'].includes(data.status)) location.reload();
      else setTimeout(poll,2000);
    } catch (_) { setTimeout(poll,4000); }
  }; setTimeout(poll,1500);
}
