(() => {
  'use strict';

  const MUSIC_FAMILIES = [
    {
      core: ['classic rock', 'blues rock', 'hard rock', 'roots rock', 'heartland rock', 'garage rock', 'folk rock', 'southern rock'],
      companions: ['psychedelic rock', 'glam rock', 'alternative rock', 'pub rock', 'country rock', 'power pop', 'boogie rock', 'indie rock'],
      eras: ['the 1960s and 1970s', 'the 1970s', 'the 1980s and 1990s', 'classic and modern rock', 'the 1970s through today', 'mostly recent releases with classic-rock roots'],
      textures: ['warm electric guitars and live drums', 'crunchy riffs and melodic leads', 'raw guitars and roomy drums', 'prominent bass and guitar interplay', 'big choruses and organic production', 'guitar-driven arrangements with a vintage edge', 'strong rhythm guitars and clear vocals', 'live-sounding drums and expressive guitars'],
    },
    {
      core: ['soul', 'funk', 'neo-soul', 'R&B', 'disco-funk', 'boogie', 'modern soul', 'deep funk'],
      companions: ['quiet storm', 'jazz-funk', 'dance-soul', 'gospel soul', 'disco', 'soul jazz', 'alt-R&B', 'funk rock'],
      eras: ['the late 1960s and 1970s', 'the 1970s and 1980s', 'the 1990s through today', 'classic soul and modern neo-soul', 'vintage and contemporary soul', 'mostly recent soul and funk'],
      textures: ['deep basslines and crisp drums', 'warm horns and tight rhythm sections', 'syncopated bass and bright brass', 'silky keys and pocket drumming', 'danceable grooves and expressive vocals', 'warm grooves with clean modern production', 'strong bass and rhythmic guitar', 'layered vocals over tight grooves'],
    },
    {
      core: ['indie rock', 'alternative rock', 'dream pop', 'shoegaze', 'indie pop', 'post-punk revival', 'jangle pop', 'art rock'],
      companions: ['noise pop', 'slowcore', 'garage revival', 'indietronica', 'college rock', 'post-rock', 'alt-pop', 'new wave'],
      eras: ['the 1980s and 1990s', 'the 1990s and 2000s', 'the 2000s and 2010s', 'mostly recent releases', 'college rock through current indie', 'the last two decades'],
      textures: ['textured guitars and atmospheric production', 'jangly guitars and melodic bass', 'hazy guitars with clear hooks', 'angular rhythms and spacious passages', 'lo-fi character with polished highlights', 'guitar ambience and subtle synths', 'dry drums and layered guitars', 'melodic bass with restrained production'],
    },
    {
      core: ['house', 'deep house', 'electro', 'synthwave', 'downtempo', 'electronica', 'techno', 'nu-disco'],
      companions: ['ambient techno', 'trip-hop', 'French touch', 'IDM', 'organic electronic', 'electro-pop', 'minimal house', 'chillwave'],
      eras: ['the 1980s through today', 'the 1990s and 2000s', 'the 2000s and 2010s', 'mostly recent electronic music', 'classic club music and current releases', 'the last two decades'],
      textures: ['layered synths and clean low end', 'warm pads and pulsing bass', 'bright arpeggios and crisp beats', 'deep bass and spacious production', 'hypnotic grooves and gradual texture changes', 'detailed percussion and restrained synths', 'analog-style synths and tight drums', 'minimal beats with rich synth layers'],
    },
    {
      core: ['jazz', 'soul jazz', 'jazz fusion', 'cool jazz', 'hard bop', 'contemporary jazz', 'modal jazz', 'vocal jazz'],
      companions: ['spiritual jazz', 'jazz-funk', 'Latin jazz', 'post-bop', 'smooth jazz', 'avant-garde jazz', 'big band', 'nu jazz'],
      eras: ['the 1950s and 1960s', 'the 1960s and 1970s', 'the 1970s through modern jazz', 'classic and contemporary jazz', 'mostly modern jazz', 'post-bop through today'],
      textures: ['acoustic ensembles and natural dynamics', 'brass over expressive rhythm sections', 'spacious arrangements and strong interplay', 'rhythmic improvisation and memorable themes', 'warm acoustic tones with some electric color', 'detailed ensemble playing', 'prominent piano and horn interplay', 'natural drums and expressive soloing'],
    },
    {
      core: ['Delta blues', 'electric blues', 'Chicago blues', 'blues rock', 'country blues', 'modern blues', 'Texas blues', 'soul blues'],
      companions: ['swamp blues', 'boogie blues', 'roots rock', 'gospel blues', 'blues soul', 'hill country blues', 'British blues', 'acoustic blues'],
      eras: ['the 1940s through 1960s', 'the 1950s through 1970s', 'classic blues and blues rock', 'traditional and modern blues', 'the 1960s through today', 'mostly modern blues with older roots'],
      textures: ['gritty guitars and expressive vocals', 'slide guitar and harmonica', 'raw electric guitar and acoustic roots', 'shuffle rhythms and dynamic playing', 'minimal arrangements and strong phrasing', 'warm amps and deep groove', 'earthy rhythm sections and bent guitar lines', 'live-sounding guitars and harmonica'],
    },
    {
      core: ['pop', 'synth-pop', 'dance-pop', 'art pop', 'power pop', 'electropop', 'indie pop', 'pop rock'],
      companions: ['sophisti-pop', 'disco pop', 'alt-pop', 'new wave pop', 'dream pop', 'dance-rock', 'bedroom pop', 'retro pop'],
      eras: ['the 1980s and 1990s', 'the 1990s and 2000s', 'the 2000s and 2010s', 'mostly recent releases', 'classic pop and newer production', 'the last two decades'],
      textures: ['strong melodies and polished rhythm sections', 'bright synths and punchy drums', 'clean production with guitar detail', 'hook-heavy arrangements and layered vocals', 'danceable bass and crisp production', 'vocal-forward songs with colorful synths', 'tight drums and memorable choruses', 'clean guitars with modern synth layers'],
    },
    {
      core: ['heavy metal', 'hard rock', 'doom metal', 'progressive metal', 'stoner metal', 'alternative metal', 'classic metal', 'groove metal'],
      companions: ['NWOBHM', 'sludge metal', 'post-metal', 'heavy psych', 'thrash metal', 'progressive rock', 'desert rock', 'metalcore'],
      eras: ['the 1970s and 1980s', 'the 1980s and 1990s', 'the 1990s and 2000s', 'classic and modern heavy music', 'the 1980s through today', 'mostly recent heavy music'],
      textures: ['thick guitar riffs and powerful drums', 'heavy low end and memorable riffs', 'dark guitar tones and dramatic builds', 'technical playing with strong hooks', 'fuzz-heavy guitars and spacious breaks', 'aggressive drums with clear contrast', 'dense riffs and punchy production', 'heavy guitars with strong rhythmic drive'],
    },
    {
      core: ['punk rock', 'post-punk', 'new wave', 'garage punk', 'power pop', 'punk-funk', 'proto-punk', 'dance-punk'],
      companions: ['art punk', 'ska punk', 'college rock', 'gothic post-punk', 'hardcore punk', 'garage rock', 'indie rock', 'cold wave'],
      eras: ['the late 1970s and early 1980s', 'the 1980s', 'the 1990s and 2000s', 'classic punk and modern descendants', 'proto-punk through today', 'mostly recent post-punk'],
      textures: ['tight drums and wiry guitars', 'driving bass and lean arrangements', 'raw energy and sharp hooks', 'fast songs with a few slower turns', 'dry production and prominent bass', 'urgent vocals and rhythmic guitars', 'stripped-down guitars and punchy drums', 'angular guitar lines and steady bass'],
    },
    {
      core: ['folk', 'Americana', 'alt-country', 'country rock', 'singer-songwriter', 'roots music', 'indie folk', 'outlaw country'],
      companions: ['bluegrass', 'cosmic country', 'folk rock', 'Gothic Americana', 'traditional country', 'acoustic pop', 'roots rock', 'country soul'],
      eras: ['the 1960s and 1970s', 'the 1970s through 1990s', 'classic and modern Americana', 'mostly recent roots music', 'traditional songwriting through today', 'the last two decades'],
      textures: ['acoustic guitars and natural vocals', 'fingerpicked guitars and pedal steel', 'story-focused songs and organic arrangements', 'earthy production and acoustic instruments', 'close harmonies and spacious instrumentation', 'roomy performances with little polish', 'acoustic rhythm with subtle electric color', 'pedal steel and understated drums'],
    },
    {
      core: ['hip-hop', 'boom bap', 'alternative hip-hop', 'jazz rap', 'conscious hip-hop', 'instrumental hip-hop', 'East Coast hip-hop', 'West Coast hip-hop'],
      companions: ['neo-soul rap', 'abstract hip-hop', 'trip-hop', 'modern lyrical rap', 'lo-fi hip-hop', 'funk rap', 'underground hip-hop', 'experimental hip-hop'],
      eras: ['the late 1980s and 1990s', 'the 1990s and early 2000s', 'the 2000s and 2010s', 'golden-era and current hip-hop', 'classic and contemporary hip-hop', 'mostly recent releases'],
      textures: ['sample-rich beats and defined drums', 'dusty drums and jazz samples', 'minimal beats with space for vocals', 'warm samples and modern low end', 'distinctive beats with strong bass', 'head-nod grooves and atmospheric breaks', 'crisp drums and layered samples', 'deep bass with restrained production'],
    },
    {
      core: ['reggae', 'dub', 'Afrobeat', 'highlife', 'cumbia', 'Latin funk', 'roots reggae', 'Afro-funk'],
      companions: ['rocksteady', 'salsa', 'tropical psychedelia', 'global groove', 'Latin soul', 'reggae fusion', 'Caribbean funk', 'desert blues'],
      eras: ['the 1960s and 1970s', 'the 1970s and 1980s', 'classic and modern global grooves', 'the 1990s through today', 'traditional and current scenes', 'mostly recent releases with older roots'],
      textures: ['interlocking percussion and deep bass', 'spacious rhythms and bright guitar accents', 'live percussion and warm horns', 'dub space and organic instrumentation', 'polyrhythms with melodic hooks', 'bass-forward production and lively ensembles', 'syncopated guitars and layered percussion', 'strong bass with bright horn lines'],
    },
    {
      core: ['ambient', 'modern classical', 'neoclassical', 'minimalism', 'drone', 'post-classical', 'piano ambient', 'cinematic instrumental'],
      companions: ['electro-acoustic', 'chamber music', 'dark ambient', 'field-recording ambient', 'minimal piano', 'modern composition', 'ambient electronic', 'instrumental post-rock'],
      eras: ['the 1970s through today', 'the 1990s through today', 'mostly recent releases', 'modern classical and contemporary ambient', 'the last two decades', 'classic minimalism and current composers'],
      textures: ['soft piano and spacious strings', 'slow synth layers and acoustic detail', 'minimal motifs and long decays', 'quiet electronics and natural ambience', 'restrained strings and subtle piano', 'wide spaces and slow harmonic movement', 'acoustic instruments with light electronic texture', 'gentle repetition and sparse arrangements'],
    },
    {
      core: ['bossa nova', 'MPB', 'samba', 'Latin jazz', 'salsa', 'Latin rock', 'tropicalia', 'Brazilian soul'],
      companions: ['bolero', 'son cubano', 'Latin funk', 'Afro-Cuban jazz', 'Latin pop', 'cumbia', 'mambo', 'Brazilian jazz'],
      eras: ['the 1950s through 1970s', 'the 1960s and 1970s', 'the 1980s through today', 'classic and modern Latin music', 'mostly recent Latin releases', 'traditional recordings and contemporary artists'],
      textures: ['acoustic guitar and light percussion', 'bright horns and syncopated rhythm sections', 'warm percussion and melodic bass', 'piano-led grooves and brass', 'organic percussion and expressive vocals', 'acoustic rhythm with colorful horn lines', 'danceable percussion and clean guitar', 'layered percussion with warm acoustic instruments'],
    },
  ];

  const MOODS = [
    'upbeat', 'relaxed', 'high-energy', 'laid-back', 'melancholic', 'bright', 'dark',
    'driving', 'mellow', 'dreamy', 'gritty', 'smooth', 'celebratory', 'moody',
    'intimate', 'playful', 'restless', 'calm',
  ];

  const CONTEXTS = [
    'a late-night drive', 'a long road trip', 'a slow Sunday morning',
    'cooking with friends', 'a focused work session', 'a sunset outdoors',
    'a lively dinner party', 'a gym session', 'a rainy evening',
    'a summer afternoon', 'a train journey', 'a weekend morning in the city',
    'a small gathering', 'an evening walk', 'an afternoon by the water',
    'discovering new music', 'a creative session', 'a weekend drive',
    'a quiet evening at home', 'a morning commute', 'a rooftop evening',
    'a relaxed dinner',
  ];

  const CREATIVE_DIRECTIONS = [
    'Include a few lesser-known tracks alongside familiar choices.',
    'Favor deeper album cuts over the most obvious hits.',
    'Keep the energy steady from start to finish.',
    'Let the energy keep rising toward the end.',
    'Let the energy keep falling toward the end.',
    'Keep transitions smooth between tracks.',
    'Use familiar tracks sparingly and leave room for discoveries.',
    'Keep the sequence varied without sharp stylistic jumps.',
    'Favor strong melodies over extreme stylistic detours.',
  ];

  const CLAUSE_BUILDERS = {
    mood: (value) => pick([
      `with a ${value} feel`,
      `that feels ${value}`,
      `with a ${value} mood`,
    ]),
    context: (value) => pick([
      `for ${value}`,
      `suited to ${value}`,
      `for listening during ${value}`,
    ]),
    era: (value) => pick([
      `mostly from ${value}`,
      `focused on ${value}`,
      `drawing mainly from ${value}`,
    ]),
    texture: (value) => pick([
      `with ${value}`,
      `favoring ${value}`,
      `built around ${value}`,
    ]),
  };

  const OPENERS = [
    (genres) => `Create a ${genres} playlist`,
    (genres) => `Make a ${genres} playlist`,
    (genres) => `Build a playlist around ${genres}`,
    (genres) => `Put together a ${genres} playlist`,
    (genres) => `Curate a ${genres} playlist`,
    (genres) => `I want a ${genres} playlist`,
  ];

  const PROFILES = {
    example: {
      minWords: 10,
      maxWords: 20,
      extraDimensions: () => (Math.random() < 0.72 ? 1 : 2),
      creativeChance: 0,
    },
    surprise: {
      minWords: 18,
      maxWords: 36,
      extraDimensions: () => (Math.random() < 0.72 ? 2 : 3),
      creativeChance: 0.28,
    },
  };

  let previousPrompt = '';
  const FAMILY_HISTORY_SIZE = Math.min(5, MUSIC_FAMILIES.length - 1);
  let recentFamilies = [];
  let previousOpener = null;

  function pick(items) {
    return items[Math.floor(Math.random() * items.length)];
  }

  function pickDifferent(items, first) {
    const alternatives = items.filter((item) => item !== first);
    return pick(alternatives.length ? alternatives : items);
  }

  function shuffled(items) {
    const copy = [...items];
    for (let index = copy.length - 1; index > 0; index -= 1) {
      const target = Math.floor(Math.random() * (index + 1));
      [copy[index], copy[target]] = [copy[target], copy[index]];
    }
    return copy;
  }

  function pickFamily() {
    const available = MUSIC_FAMILIES.filter((family) => !recentFamilies.includes(family));
    const family = pick(available.length ? available : MUSIC_FAMILIES);
    recentFamilies = [family, ...recentFamilies].slice(0, FAMILY_HISTORY_SIZE);
    return family;
  }

  function pickOpener() {
    const opener = OPENERS.length > 1 ? pickDifferent(OPENERS, previousOpener) : pick(OPENERS);
    previousOpener = opener;
    return opener;
  }

  function wordCount(value) {
    return String(value).trim().split(/\s+/).filter(Boolean).length;
  }

  function buildGenrePhrase(family) {
    const primary = pick(family.core);
    if (Math.random() >= 0.64) return primary;
    const companion = pickDifferent([...family.core, ...family.companions], primary);
    return `${primary} and ${companion}`;
  }

  function rawPrompt(profileName) {
    const profile = PROFILES[profileName];
    const family = pickFamily();
    const genres = buildGenrePhrase(family);
    const dimensions = shuffled([
      ['mood', pick(MOODS)],
      ['context', pick(CONTEXTS)],
      ['era', pick(family.eras)],
      ['texture', pick(family.textures)],
    ]).slice(0, profile.extraDimensions());

    const clauses = dimensions.map(([kind, value]) => CLAUSE_BUILDERS[kind](value));
    const sentence = `${pickOpener()(genres)} ${clauses.join(', ')}.`;

    if (Math.random() < profile.creativeChance) {
      return `${sentence} ${pick(CREATIVE_DIRECTIONS)}`;
    }
    return sentence;
  }

  function buildPrompt(profileName = 'surprise') {
    const profile = PROFILES[profileName] || PROFILES.surprise;
    let closest = '';
    let closestDistance = Number.POSITIVE_INFINITY;

    for (let attempt = 0; attempt < 32; attempt += 1) {
      const candidate = rawPrompt(profileName);
      const words = wordCount(candidate);
      if (words >= profile.minWords && words <= profile.maxWords) return candidate;

      const distance = words < profile.minWords
        ? profile.minWords - words
        : words - profile.maxWords;
      if (distance < closestDistance) {
        closest = candidate;
        closestDistance = distance;
      }
    }
    return closest || rawPrompt(profileName);
  }

  function init() {
    const prompt = document.getElementById('prompt');
    const button = document.getElementById('prompt-surprise');
    if (!prompt) return;

    function surpriseMe() {
      let next = buildPrompt('surprise');
      for (let attempt = 0; attempt < 8 && next === previousPrompt; attempt += 1) {
        next = buildPrompt('surprise');
      }
      previousPrompt = next;

      prompt.value = next;
      prompt.dispatchEvent(new Event('input', {bubbles: true}));
      prompt.focus();
      prompt.setSelectionRange(prompt.value.length, prompt.value.length);
    }

    const example = buildPrompt('example');
    prompt.placeholder = example;
    previousPrompt = example;

    button?.addEventListener('click', surpriseMe);
  }

  window.PlaylistMusePromptSurprise = {buildPrompt, MUSIC_FAMILIES, CREATIVE_DIRECTIONS, pickFamily};
  if (typeof document !== 'undefined') init();
})();
