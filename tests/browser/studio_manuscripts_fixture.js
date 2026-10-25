/* Test-only browser helpers for the isolated manuscript reader. */
(() => {
  window.__studioManuscriptErrors = [];
  addEventListener('error', event => window.__studioManuscriptErrors.push(String(event.message || '')));
  addEventListener('unhandledrejection', event => window.__studioManuscriptErrors.push(String(event.reason?.stack || event.reason || '')));
  window.__studioManuscriptClipboard = '';
  try {
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: async value => { window.__studioManuscriptClipboard = String(value); } }
    });
  } catch (_) {}
  window.confirm = () => true;
  window.__studioManuscript = {
    setText(id, value, composing = false) {
      const field = document.getElementById(id);
      field.value = value;
      field.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: value, isComposing: composing }));
    },
    fireComposition(id, name) {
      document.getElementById(id).dispatchEvent(new CompositionEvent(name, { bubbles: true, data: '' }));
    },
    fireInlineComposition(key, name) {
      const field = [...document.querySelectorAll('.sm-inline-input')].find(item => item.dataset.inlineKey === key);
      if (!field) throw new Error(`inline field missing: ${key}`);
      field.dispatchEvent(new CompositionEvent(name, { bubbles: true, data: '' }));
    },
    waitFor(predicate, timeout = 5000) {
      return new Promise((resolve, reject) => {
        const started = performance.now();
        const poll = () => {
          try {
            if (predicate()) return resolve(true);
            if (performance.now() - started > timeout) return reject(new Error('fixture wait timeout'));
          } catch (error) {
            if (performance.now() - started > timeout) return reject(error);
          }
          setTimeout(poll, 25);
        };
        poll();
      });
    }
  };
})();
