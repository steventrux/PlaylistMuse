(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const providerDefaults = {
    gemini: {
      primary: 'gemini-3.6-flash',
      fallback1: 'gemini-3.5-flash',
      fallback2: 'gemini-3.5-flash-lite',
      help: 'Create or manage a Gemini API key',
      href: 'https://aistudio.google.com/app/apikey',
    },
    openai: {
      primary: 'gpt-5-mini',
      fallback1: 'gpt-4.1-mini',
      fallback2: 'gpt-4.1-nano',
      help: 'Create or manage an OpenAI API key',
      href: 'https://platform.openai.com/api-keys',
    },
    anthropic: {
      primary: 'claude-sonnet-4-5',
      fallback1: 'claude-haiku-4-5',
      fallback2: '',
      help: 'Create or manage an Anthropic API key',
      href: 'https://console.anthropic.com/settings/keys',
    },
    ollama: {
      primary: 'qwen3:8b',
      fallback1: 'llama3.1:8b',
      fallback2: '',
      help: 'Ollama runs models on your own server',
      href: 'https://ollama.com/library',
    },
    custom: {
      primary: '',
      fallback1: '',
      fallback2: '',
      help: 'Use any OpenAI-compatible chat-completions endpoint',
      href: 'https://platform.openai.com/docs/api-reference/chat',
    },
  };

  let loadedProvider = '';

  async function readJson(response) {
    const text = await response.text();
    let data = {};
    try { data = text ? JSON.parse(text) : {}; }
    catch { throw new Error(text || `HTTP ${response.status}`); }
    if (!response.ok) {
      const detail = data.detail ?? data.error ?? data.message;
      throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail || data));
    }
    return data;
  }

  function setProviderFields({applyDefaults = false} = {}) {
    const provider = $('ai-provider').value;
    const defaults = providerDefaults[provider] || providerDefaults.custom;
    const local = provider === 'ollama';
    const custom = provider === 'custom';

    $('api-key-field').classList.toggle('hidden', local);
    $('base-url-field').classList.toggle('hidden', !(local || custom));
    $('provider-help-link').textContent = defaults.help;
    $('provider-help-link').href = defaults.href;

    if (local) {
      $('ai-base-url').placeholder = 'http://host:11434';
      $('api-key-hint').textContent = 'Ollama does not require an API key.';
    } else if (custom) {
      $('ai-base-url').placeholder = 'https://example.com/v1';
      $('api-key-hint').textContent = 'Optional when the custom endpoint does not require authentication.';
    } else {
      $('api-key-hint').textContent = 'Leave blank when saving to keep the stored key.';
    }

    if (applyDefaults) {
      $('ai-model').value = defaults.primary;
      $('ai-fallback-1').value = defaults.fallback1;
      $('ai-fallback-2').value = defaults.fallback2;
    }
  }

  async function loadSettings() {
    $('ai-status').textContent = 'Checking AI configuration…';
    try {
      const data = await readJson(await fetch('/api/settings'));
      loadedProvider = data.provider || 'gemini';
      $('ai-provider').value = loadedProvider;
      $('ai-model').value = data.model || providerDefaults[loadedProvider]?.primary || '';
      $('ai-fallback-1').value = data.fallback_1 || providerDefaults[loadedProvider]?.fallback1 || '';
      $('ai-fallback-2').value = data.fallback_2 || providerDefaults[loadedProvider]?.fallback2 || '';
      $('ai-base-url').value = data.base_url || '';
      $('ai-key').value = '';
      setProviderFields();

      if (data.configured) {
        const chain = [data.model, data.fallback_1, data.fallback_2].filter(Boolean).join(' → ');
        $('ai-status').textContent = `Configured: ${chain}`;
        $('ai-status').classList.add('ok');
      } else {
        $('ai-status').textContent = 'AI provider configuration required.';
        $('ai-status').classList.remove('ok');
      }
    } catch (error) {
      $('ai-status').textContent = error.message || String(error);
      $('ai-status').classList.remove('ok');
    }
  }

  async function saveSettings() {
    const button = $('save-ai');
    button.disabled = true;
    button.textContent = 'Saving…';
    $('ai-status').textContent = 'Saving AI settings…';

    try {
      const data = await readJson(await fetch('/api/settings', {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          provider: $('ai-provider').value,
          api_key: $('ai-key').value.trim(),
          model: $('ai-model').value.trim(),
          fallback_1: $('ai-fallback-1').value.trim(),
          fallback_2: $('ai-fallback-2').value.trim(),
          base_url: $('ai-base-url').value.trim(),
        }),
      }));

      loadedProvider = data.provider;
      $('ai-key').value = '';
      const chain = [data.model, data.fallback_1, data.fallback_2].filter(Boolean).join(' → ');
      $('ai-status').textContent = data.configured
        ? `Saved: ${chain}`
        : 'Saved, but the provider is not fully configured.';
      $('ai-status').classList.toggle('ok', data.configured);
      window.dispatchEvent(new Event('playlistmuse-status-changed'));
    } catch (error) {
      $('ai-status').textContent = error.message || String(error);
      $('ai-status').classList.remove('ok');
    } finally {
      button.disabled = false;
      button.textContent = 'Save AI settings';
    }
  }

  $('ai-provider').addEventListener('change', () => {
    setProviderFields({applyDefaults: $('ai-provider').value !== loadedProvider});
  });
  $('save-ai').addEventListener('click', saveSettings);
  window.addEventListener('playlistmuse-settings-opened', loadSettings);
})();
