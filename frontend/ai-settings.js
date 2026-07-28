(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const providerDefaults = {
    gemini: {
      label: 'Google Gemini',
      primary: 'gemini-3.6-flash',
      fallback1: 'gemini-3.5-flash',
      fallback2: 'gemini-3.5-flash-lite',
      help: 'Create or manage a Gemini API key',
      href: 'https://aistudio.google.com/app/apikey',
    },
    openai: {
      label: 'OpenAI',
      primary: 'gpt-5-mini',
      fallback1: 'gpt-4.1-mini',
      fallback2: 'gpt-4.1-nano',
      help: 'Create or manage an OpenAI API key',
      href: 'https://platform.openai.com/api-keys',
    },
    anthropic: {
      label: 'Anthropic',
      primary: 'claude-sonnet-4-5',
      fallback1: 'claude-haiku-4-5',
      fallback2: '',
      help: 'Create or manage an Anthropic API key',
      href: 'https://console.anthropic.com/settings/keys',
    },
    openrouter_auto: {
      label: 'OpenRouter Auto',
      primary: 'openrouter/auto',
      fallback1: '',
      fallback2: '',
      help: 'Create or manage an OpenRouter API key',
      href: 'https://openrouter.ai/settings/keys',
    },
    openrouter_free: {
      label: 'OpenRouter Free',
      primary: 'openrouter/free',
      fallback1: '',
      fallback2: '',
      help: 'Create or manage an OpenRouter API key',
      href: 'https://openrouter.ai/settings/keys',
    },
    ollama: {
      label: 'Ollama',
      primary: 'qwen3:8b',
      fallback1: 'llama3.1:8b',
      fallback2: '',
      help: 'Ollama runs models on your own server',
      href: 'https://ollama.com/library',
    },
    custom: {
      label: 'OpenAI-compatible endpoint',
      primary: '',
      fallback1: '',
      fallback2: '',
      help: 'Use any OpenAI-compatible chat-completions endpoint',
      href: 'https://platform.openai.com/docs/api-reference/chat',
    },
  };

  let loadedProvider = '';
  let loadedSettings = null;
  let providerKeysSet = {};
  let configuredProviders = {};

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

  function refreshProviderLabels() {
    Array.from($('ai-provider').options).forEach((option) => {
      const defaults = providerDefaults[option.value] || providerDefaults.custom;
      const configured = Boolean(configuredProviders[option.value] || providerKeysSet[option.value]);
      option.textContent = `${configured ? '✓ ' : ''}${defaults.label}`;
    });
  }

  function applyProviderValues(provider) {
    const defaults = providerDefaults[provider] || providerDefaults.custom;
    const values = provider === loadedProvider && loadedSettings
      ? loadedSettings
      : {
          model: defaults.primary,
          fallback_1: defaults.fallback1,
          fallback_2: defaults.fallback2,
          base_url: '',
        };

    $('ai-model').value = values.model || defaults.primary;
    $('ai-fallback-1').value = values.fallback_1 || '';
    $('ai-fallback-2').value = values.fallback_2 || '';
    $('ai-base-url').value = values.base_url || '';
  }

  function setProviderFields() {
    const provider = $('ai-provider').value;
    const defaults = providerDefaults[provider] || providerDefaults.custom;
    const local = provider === 'ollama';
    const custom = provider === 'custom';
    const openRouter = provider === 'openrouter_auto' || provider === 'openrouter_free';
    const keyStored = Boolean(providerKeysSet[provider]);

    $('api-key-field').classList.toggle('hidden', local);
    $('base-url-field').classList.toggle('hidden', !(local || custom));
    $('fallback-row').classList.toggle('hidden', openRouter);
    $('ai-model').readOnly = openRouter;
    $('ai-model').setAttribute('aria-readonly', String(openRouter));
    $('provider-help-link').textContent = defaults.help;
    $('provider-help-link').href = defaults.href;

    if (local) {
      $('ai-base-url').placeholder = 'http://host:11434';
      $('api-key-hint').textContent = 'Ollama does not require an API key.';
    } else if (custom) {
      $('ai-base-url').placeholder = 'https://example.com/v1';
      $('api-key-hint').textContent = keyStored
        ? 'A key is already saved for this endpoint. Leave blank to keep it.'
        : 'Optional when the custom endpoint does not require authentication.';
    } else if (openRouter) {
      $('api-key-hint').textContent = keyStored
        ? 'OpenRouter key saved. The same key is shared by Auto and Free.'
        : 'One OpenRouter API key is shared by the Auto and Free modes.';
    } else {
      $('api-key-hint').textContent = keyStored
        ? 'API key already saved. Leave blank to keep it.'
        : 'Enter an API key for this provider.';
    }
  }

  async function loadSettings() {
    $('ai-status').textContent = 'Checking AI configuration…';
    try {
      const data = await readJson(await fetch('/api/settings'));
      loadedProvider = data.provider || 'gemini';
      loadedSettings = {
        model: data.model || '',
        fallback_1: data.fallback_1 || '',
        fallback_2: data.fallback_2 || '',
        base_url: data.base_url || '',
      };
      providerKeysSet = data.provider_keys_set || {};
      configuredProviders = {};
      if (data.configured && loadedProvider) configuredProviders[loadedProvider] = true;

      $('ai-provider').value = loadedProvider;
      $('ai-key').value = '';
      applyProviderValues(loadedProvider);
      setProviderFields();
      refreshProviderLabels();

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
      loadedSettings = {
        model: data.model || '',
        fallback_1: data.fallback_1 || '',
        fallback_2: data.fallback_2 || '',
        base_url: data.base_url || '',
      };
      providerKeysSet = data.provider_keys_set || {};
      configuredProviders = {};
      if (data.configured && loadedProvider) configuredProviders[loadedProvider] = true;
      $('ai-key').value = '';
      applyProviderValues(loadedProvider);
      setProviderFields();
      refreshProviderLabels();

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
    applyProviderValues($('ai-provider').value);
    setProviderFields();
  });
  $('save-ai').addEventListener('click', saveSettings);
  window.addEventListener('playlistmuse-settings-opened', loadSettings);
})();
