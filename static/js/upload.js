// drag-and-drop for any .dropzone (file input inside)
document.querySelectorAll('.dropzone').forEach(function (dz) {
  var input = dz.querySelector('input[type=file]');
  var fileLabel = dz.querySelector('.dz-file');
  if (!input) return;
  function show() {
    if (fileLabel) fileLabel.textContent = input.files.length ? '📎 ' + input.files[0].name : '';
    dz.classList.toggle('has-file', input.files.length > 0);
  }
  input.addEventListener('change', show);
  ['dragenter', 'dragover'].forEach(function (ev) {
    dz.addEventListener(ev, function (e) { e.preventDefault(); dz.classList.add('drag'); });
  });
  ['dragleave', 'drop'].forEach(function (ev) {
    dz.addEventListener(ev, function (e) { e.preventDefault(); dz.classList.remove('drag'); });
  });
  dz.addEventListener('drop', function (e) {
    if (e.dataTransfer.files.length) { input.files = e.dataTransfer.files; show(); }
  });
});
