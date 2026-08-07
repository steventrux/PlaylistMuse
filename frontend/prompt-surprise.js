(() => {
  'use strict';

  const prompt = document.getElementById('prompt');
  const button = document.getElementById('prompt-surprise');
  if (!prompt || !button) return;

  const MUSIC_FAMILIES = [
    {
      core: ['classic rock', 'blues rock', 'hard rock', 'roots rock', 'heartland rock', 'garage rock'],
      companions: ['southern rock', 'psychedelic rock', 'glam rock', 'alternative rock', 'folk rock', 'pub rock'],
      eras: ['late 1960s and 1970s', '1970s and early 1980s', '1980s and 1990s', 'mixed eras from the 1960s to today', 'modern tracks with strong classic-rock roots'],
      textures: ['warm electric guitars and live-sounding drums', 'crunchy riffs and melodic guitar leads', 'raw guitars, roomy drums and expressive vocals', 'big choruses balanced by deeper album cuts', 'organic production with prominent bass and guitar interplay', 'guitar-driven arrangements with a slightly vintage feel'],
    },
    {
      core: ['soul', 'funk', 'neo-soul', 'R&B', 'disco-funk', 'boogie'],
      companions: ['deep funk', 'quiet storm', 'modern soul', 'jazz-funk', 'dance-soul', 'gospel-inflected soul'],
      eras: ['late 1960s and 1970s', '1970s and 1980s', '1990s through today', 'classic soul through contemporary neo-soul', 'a cross-era mix of vintage and modern productions'],
      textures: ['elastic basslines, crisp drums and warm horns', 'deep grooves with expressive vocals and rich rhythm sections', 'syncopated bass, clavinet and bright brass accents', 'silky keys, pocket drumming and soulful vocal performances', 'danceable rhythm sections without losing musical detail', 'warm analog-style grooves mixed with cleaner modern production'],
    },
    {
      core: ['indie rock', 'alternative rock', 'dream pop', 'shoegaze', 'indie pop', 'post-punk revival'],
      companions: ['art rock', 'jangle pop', 'noise pop', 'slowcore', 'garage revival', 'indietronica'],
      eras: ['1980s and 1990s influences', '1990s and 2000s', '2000s and 2010s', 'mostly contemporary releases', 'mixed eras from college rock to current indie'],
      textures: ['textured guitars and atmospheric production', 'jangly guitars, melodic bass and dry drums', 'hazy layers with strong melodic hooks', 'angular rhythms balanced by spacious passages', 'lo-fi character mixed with polished standout tracks', 'guitar ambience, synth accents and intimate vocals'],
    },
    {
      core: ['house', 'deep house', 'electro', 'synthwave', 'downtempo', 'electronica'],
      companions: ['nu-disco', 'ambient techno', 'trip-hop', 'French touch', 'IDM', 'organic electronic'],
      eras: ['1980s electronic influences through today', '1990s and 2000s club music', '2000s and 2010s', 'mostly contemporary electronic releases', 'a cross-era mix of foundational and modern electronic music'],
      textures: ['layered synths, clean low end and detailed percussion', 'warm pads, pulsing bass and restrained electronic drums', 'bright arpeggios, analog-style synths and crisp beats', 'deep bass, spacious production and subtle rhythmic detail', 'hypnotic grooves with gradual textural changes', 'electronic production that feels immersive rather than overly maximal'],
    },
    {
      core: ['jazz', 'soul jazz', 'jazz fusion', 'cool jazz', 'hard bop', 'contemporary jazz'],
      companions: ['modal jazz', 'spiritual jazz', 'jazz-funk', 'vocal jazz', 'Latin jazz', 'ECM-style jazz'],
      eras: ['1950s and 1960s', '1960s and 1970s', '1970s fusion through modern jazz', 'classic recordings mixed with contemporary players', 'a cross-era journey from hard bop to current jazz'],
      textures: ['acoustic ensembles with strong interplay and natural dynamics', 'brass and woodwinds over expressive rhythm sections', 'spacious arrangements with detailed instrumental conversations', 'rhythmic improvisation balanced by memorable themes', 'warm acoustic tones with occasional electric textures', 'performances that prioritize feel, phrasing and ensemble chemistry'],
    },
    {
      core: ['Delta blues', 'electric blues', 'Chicago blues', 'blues rock', 'country blues', 'modern blues'],
      companions: ['Texas blues', 'swamp blues', 'soul blues', 'boogie blues', 'roots rock', 'gospel blues'],
      eras: ['1940s through 1960s', '1950s through 1970s', 'classic blues through the blues-rock era', 'traditional recordings mixed with modern revivalists', 'a cross-era blues journey from acoustic roots to current artists'],
      textures: ['gritty guitar tones, expressive vocals and a strong live feel', 'slide guitar, harmonica and earthy rhythm sections', 'raw electric guitar balanced by acoustic roots', 'shuffle rhythms, bent notes and dynamic performances', 'minimal arrangements where phrasing matters more than polish', 'deep groove, warm amps and emotionally direct playing'],
    },
    {
      core: ['pop', 'synth-pop', 'dance-pop', 'art pop', 'power pop', 'electropop'],
      companions: ['indie pop', 'sophisti-pop', 'pop rock', 'disco pop', 'alt-pop', 'new wave pop'],
      eras: ['1980s and 1990s', '1990s and 2000s', '2000s and 2010s', 'mostly contemporary releases', 'a cross-era mix of enduring hooks and newer production'],
      textures: ['strong melodies, polished rhythm sections and memorable hooks', 'bright synths, punchy drums and layered vocals', 'clean pop production with enough instrumental character', 'hook-heavy arrangements balanced by a few left-field choices', 'danceable low end with crisp, melodic production', 'vocal-forward songs with colorful synth and guitar details'],
    },
    {
      core: ['heavy metal', 'hard rock', 'doom metal', 'progressive metal', 'stoner metal', 'alternative metal'],
      companions: ['NWOBHM', 'groove metal', 'sludge metal', 'post-metal', 'heavy psych', 'classic metal'],
      eras: ['1970s and 1980s foundations', '1980s and 1990s', '1990s and 2000s', 'classic metal mixed with modern heavy music', 'a cross-era mix from early heavy metal to current releases'],
      textures: ['thick guitar riffs, powerful drums and clear dynamic shifts', 'heavy low end with memorable riffs rather than constant maximalism', 'dark guitar tones, weighty drums and dramatic builds', 'technical playing balanced by strong songs and hooks', 'fuzz-heavy guitars with spacious, slower passages', 'aggressive rhythm sections with enough contrast to keep the sequence moving'],
    },
    {
      core: ['punk rock', 'post-punk', 'new wave', 'garage punk', 'power pop', 'punk-funk'],
      companions: ['proto-punk', 'art punk', 'dance-punk', 'ska punk', 'college rock', 'gothic post-punk'],
      eras: ['late 1970s and early 1980s', '1980s underground scenes', '1990s and 2000s revivals', 'classic punk mixed with modern descendants', 'a cross-era path from proto-punk to current post-punk'],
      textures: ['tight drums, wiry guitars and direct vocal performances', 'angular guitar lines, driving bass and lean arrangements', 'raw energy balanced by sharp hooks', 'fast, concise songs with occasional moodier detours', 'dry production, prominent bass and rhythmic guitar interplay', 'urgent performances with enough stylistic variation to avoid repetition'],
    },
    {
      core: ['folk', 'Americana', 'alt-country', 'country rock', 'singer-songwriter', 'roots music'],
      companions: ['bluegrass', 'cosmic country', 'folk rock', 'Gothic Americana', 'outlaw country', 'indie folk'],
      eras: ['1960s and 1970s', '1970s through 1990s', 'classic roots music mixed with modern Americana', 'mostly contemporary roots releases', 'a cross-era mix from traditional songwriting to current artists'],
      textures: ['acoustic guitars, natural vocals and understated rhythm sections', 'fingerpicked guitars, pedal steel and warm harmonies', 'story-focused songs with organic arrangements', 'earthy production with acoustic and lightly amplified instruments', 'close vocal harmonies and spacious roots instrumentation', 'unpolished performances that preserve room sound and character'],
    },
    {
      core: ['hip-hop', 'boom bap', 'alternative hip-hop', 'jazz rap', 'conscious hip-hop', 'instrumental hip-hop'],
      companions: ['neo-soul rap', 'abstract hip-hop', 'East Coast hip-hop', 'West Coast hip-hop', 'trip-hop', 'modern lyrical rap'],
      eras: ['late 1980s and 1990s', '1990s and early 2000s', '2000s and 2010s', 'golden-era foundations mixed with contemporary releases', 'a cross-era mix of classic and current hip-hop'],
      textures: ['sample-rich beats, defined drums and strong basslines', 'dusty drums, jazz samples and detailed production', 'minimal beats that leave space for delivery and lyricism', 'warm samples balanced by cleaner modern low end', 'rhythmic variety with distinctive production identities', 'head-nod grooves with occasional atmospheric or instrumental passages'],
    },
    {
      core: ['reggae', 'dub', 'Afrobeat', 'highlife', 'cumbia', 'Latin funk'],
      companions: ['rocksteady', 'roots reggae', 'Afro-funk', 'salsa dura', 'tropical psychedelia', 'global groove'],
      eras: ['1960s and 1970s foundations', '1970s and 1980s', 'classic recordings mixed with modern revivalists', '1990s through contemporary global grooves', 'a cross-era selection linking traditional and modern scenes'],
      textures: ['interlocking percussion, deep bass and bright guitar or horn accents', 'rhythm-first arrangements with spacious production', 'live percussion, syncopated guitars and warm horn sections', 'deep grooves with dubby space and organic instrumentation', 'polyrhythmic arrangements that stay danceable and melodic', 'bass-forward production with lively ensemble playing'],
    },
  ];

  const CONTEXTS = [
    {scene: 'a late-night drive', energy: ['low', 'medium', 'arc']},
    {scene: 'a long road trip', energy: ['medium', 'arc', 'high']},
    {scene: 'a slow Sunday morning', energy: ['low', 'medium']},
    {scene: 'an evening cooking with friends', energy: ['medium', 'arc']},
    {scene: 'a focused afternoon of work', energy: ['low', 'medium']},
    {scene: 'a sunset drink outdoors', energy: ['low', 'medium', 'arc']},
    {scene: 'a lively dinner party', energy: ['medium', 'high', 'arc']},
    {scene: 'a gym session that needs momentum', energy: ['high', 'arc']},
    {scene: 'a rainy evening indoors', energy: ['low', 'medium']},
    {scene: 'a summer afternoon with the windows open', energy: ['medium', 'high']},
    {scene: 'a train journey through changing landscapes', energy: ['low', 'medium', 'arc']},
    {scene: 'a weekend morning in the city', energy: ['medium', 'arc']},
    {scene: 'a small gathering that gradually gets louder', energy: ['arc', 'high']},
    {scene: 'an introspective walk after dark', energy: ['low', 'arc']},
    {scene: 'a relaxed afternoon by the water', energy: ['low', 'medium']},
    {scene: 'a night of discovering unfamiliar music', energy: ['medium', 'arc']},
    {scene: 'a creative session that should stay engaging', energy: ['medium', 'arc']},
    {scene: 'a weekend drive with no fixed destination', energy: ['medium', 'arc', 'high']},
  ];

  const ENERGY_ARCS = {
    low: [
      'Keep the energy restrained and consistent, with smooth transitions and no abrupt peaks',
      'Let the pace stay relaxed, allowing small dynamic changes without becoming sleepy',
      'Favor a patient flow with breathing room between the more intense moments',
      'Keep a gentle pulse throughout and use subtle changes in texture to create movement',
    ],
    medium: [
      'Maintain a steady medium-energy flow, alternating denser songs with a little breathing room',
      'Keep the momentum consistent without making every track feel equally intense',
      'Aim for an easy forward motion, using groove and contrast rather than dramatic peaks',
      'Let the sequence feel lively but controlled, with natural rises and releases',
    ],
    high: [
      'Start with momentum and keep the energy high, using only short resets before the strongest peaks',
      'Prioritize driving tracks and strong rhythmic continuity while still varying texture and tempo',
      'Keep the sequence energetic and immediate, avoiding long low-energy stretches',
      'Build around punchy, propulsive songs with a few strategic breathers to prevent fatigue',
    ],
    arc: [
      'Begin relatively restrained, build gradually through the middle, and finish with a confident peak',
      'Shape a clear arc: inviting opener, rising momentum, a brief reset, then a stronger final stretch',
      'Let the first third establish the mood, increase intensity in the middle, and end on a memorable high',
      'Use a slow-burn progression where each section feels slightly more energized than the one before it',
      'Create waves of energy rather than a straight line, with each return landing a little stronger',
    ],
  };

  const MOODS = [
    'warm', 'nocturnal', 'uplifting', 'moody', 'cinematic', 'restless', 'sun-drenched',
    'intimate', 'confident', 'dreamy', 'raw', 'elegant', 'playful', 'reflective', 'gritty',
    'hypnotic', 'romantic', 'adventurous', 'nostalgic without feeling retro-only', 'slightly mysterious',
  ];

  const DISCOVERY = [
    'Balance recognizable anchors with lesser-known tracks that genuinely fit the same musical world',
    'Lean toward deep cuts and underplayed songs, but keep a few accessible reference points',
    'Mix familiar classics with discoveries from adjacent artists instead of relying on obvious hits',
    'Favor strong album tracks and cult favorites over a greatest-hits sequence',
    'Keep the selection approachable while reserving roughly a third of the playlist for discoveries',
    'Prefer less predictable choices when two songs fit equally well',
    'Use well-known songs sparingly and let related artists carry most of the discovery value',
    'Build around quality and flow rather than popularity, without becoming deliberately obscure',
    'Include a handful of unexpected but musically defensible detours',
    'Use recognizable tracks as signposts, then explore deeper material around them',
    'Avoid stacking the most famous song from every artist; vary between hits, album cuts and discoveries',
    'Keep artist repetition low enough that the playlist feels curated rather than like a discography shuffle',
  ];

  const VOCAL_DIRECTIONS = [
    'Mix vocal tracks with occasional instrumental passages where they improve the flow',
    'Keep vocals central but vary vocal tone, range and delivery across the sequence',
    'Allow instrumental tracks only when they add a useful transition or change of texture',
    'Favor expressive performances over technically perfect but emotionally flat vocals',
    'Use a broad mix of vocal styles and avoid long runs of very similar singers',
    'Let instrumentation lead the selection; vocals should support the mood rather than dominate every choice',
    'Keep the vocal presence varied, with some intimate performances and some larger, more forceful ones',
    'Avoid making vocal gender or style a hard constraint; prioritize musical continuity',
  ];

  const SEQUENCING = [
    'Sequence by feel and musical continuity rather than chronology',
    'Use tempo, key feel and production texture to make neighboring tracks sound intentional',
    'Avoid placing several very similar tracks back-to-back; use contrast without breaking the mood',
    'Treat the first three and last three tracks as deliberate mini-sequences with a clear purpose',
    'Use occasional stylistic pivots as transitions, not as random interruptions',
    'Keep artist repetition separated and avoid obvious clusters from the same album or era',
    'Make transitions feel natural even when the playlist crosses subgenres or decades',
    'Prioritize a satisfying listening journey over strict historical ordering',
    'Use the middle of the playlist for the widest exploration, then tighten the focus near the end',
    'Alternate familiar and less familiar material so discovery never feels like a separate block',
    'Avoid a front-loaded playlist where all the strongest tracks appear in the first third',
    'End with a track that feels conclusive rather than simply choosing the highest-energy song',
  ];

  const TEMPLATES = [
    ({mood, scene, genres, era, texture, energy, discovery, sequencing, vocals}) =>
      `Create a ${mood} playlist for ${scene}, rooted in ${genres}. Draw mainly from ${era}, with ${texture}. ${energy}. ${discovery}. ${sequencing}. ${vocals}.`,
    ({mood, scene, genres, era, texture, energy, discovery, sequencing, vocals}) =>
      `Build a playlist with a ${mood} feel for ${scene}. Center it on ${genres}, using ${era} as the main time frame. I want ${texture}. ${energy}. ${sequencing}. ${discovery}. ${vocals}.`,
    ({mood, scene, genres, era, texture, energy, discovery, sequencing, vocals}) =>
      `Make a ${genres} playlist for ${scene} that feels ${mood}. Focus on ${era} and favor ${texture}. ${energy}. ${discovery}. ${vocals}. ${sequencing}.`,
    ({mood, scene, genres, era, texture, energy, discovery, sequencing, vocals}) =>
      `Curate a journey through ${genres} for ${scene}. The mood should be ${mood}, drawing mostly from ${era}. Use ${texture} as the sonic thread. ${energy}. ${sequencing}. ${discovery}. ${vocals}.`,
    ({mood, scene, genres, era, texture, energy, discovery, sequencing, vocals}) =>
      `I want a ${mood} soundtrack for ${scene}: mostly ${genres}, centered on ${era}. Favor ${texture}. ${energy}. ${discovery}. ${sequencing}. ${vocals}.`,
    ({mood, scene, genres, era, texture, energy, discovery, sequencing, vocals}) =>
      `Put together a playlist around ${genres} with a ${mood} atmosphere, suited to ${scene}. Pull primarily from ${era} and look for ${texture}. ${energy}. ${vocals}. ${discovery}. ${sequencing}.`,
  ];

  let previousPrompt = '';

  function pick(items) {
    return items[Math.floor(Math.random() * items.length)];
  }

  function pickDifferent(items, first) {
    const alternatives = items.filter((item) => item !== first);
    return pick(alternatives.length ? alternatives : items);
  }

  function buildPrompt() {
    const family = pick(MUSIC_FAMILIES);
    const primary = pick(family.core);
    const companionPool = [...family.core, ...family.companions];
    const companion = pickDifferent(companionPool, primary);
    const genres = Math.random() < 0.78 ? `${primary} and ${companion}` : primary;

    const firstMood = pick(MOODS);
    const mood = Math.random() < 0.64
      ? `${firstMood} and ${pickDifferent(MOODS, firstMood)}`
      : firstMood;

    const context = pick(CONTEXTS);
    const energyGroup = pick(context.energy);
    const values = {
      mood,
      scene: context.scene,
      genres,
      era: pick(family.eras),
      texture: pick(family.textures),
      energy: pick(ENERGY_ARCS[energyGroup]),
      discovery: pick(DISCOVERY),
      sequencing: pick(SEQUENCING),
      vocals: pick(VOCAL_DIRECTIONS),
    };

    return pick(TEMPLATES)(values);
  }

  function surpriseMe() {
    let next = buildPrompt();
    for (let attempt = 0; attempt < 6 && next === previousPrompt; attempt += 1) {
      next = buildPrompt();
    }
    previousPrompt = next;

    prompt.value = next;
    prompt.dispatchEvent(new Event('input', {bubbles: true}));
    prompt.focus();
    prompt.setSelectionRange(prompt.value.length, prompt.value.length);
  }

  button.addEventListener('click', surpriseMe);
})();
