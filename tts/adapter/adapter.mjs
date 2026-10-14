import http from 'node:http';
import fs from 'node:fs';

const PORT = 8004;
const UPSTREAM = 'http://qwen3_tts_clone:8003/v1/audio/speech';
const REFERENCE_FILE = '/voices/anziano_roco_long_v1.wav';

const referenceAudio =
    'data:audio/wav;base64,' +
    fs.readFileSync(REFERENCE_FILE).toString('base64');

const referenceText =
    'Quando ero giovane, credevo che la conoscenza fosse sufficiente a illuminare ogni sentiero. ' +
    'Con il passare degli anni ho compreso che anche il dubbio possiede una sua saggezza. ' +
    'Ascolta con attenzione, dunque, perché persino il silenzio può rivelare verità che le parole non sanno esprimere.';

const server = http.createServer(async (req, res) => {
    if (req.method === 'GET' && req.url === '/health') {
        res.writeHead(200, { 'Content-Type': 'text/plain' });
        return res.end('OK');
    }

    if (req.method !== 'POST' || req.url !== '/v1/audio/speech') {
        res.writeHead(404, { 'Content-Type': 'text/plain' });
        return res.end('Not found');
    }

    try {
        const chunks = [];
        for await (const chunk of req) chunks.push(chunk);
        const request = JSON.parse(Buffer.concat(chunks).toString('utf8'));

        if (!request.input || typeof request.input !== 'string') {
            res.writeHead(400, { 'Content-Type': 'text/plain' });
            return res.end('Missing input text');
        }

        // Keep playback responsive by default, while still allowing the
        // OpenAI-compatible client to choose a supported speaking rate.
        const requestedSpeed = Number(request.speed);
        const speed = Number.isFinite(requestedSpeed)
            ? Math.min(2, Math.max(0.5, requestedSpeed))
            : 1.1;

        const payload = {
            model: 'Qwen/Qwen3-TTS-12Hz-1.7B-Base',
            input: request.input,
            task_type: 'Base',
            language: 'Italian',
            ref_audio: referenceAudio,
            ref_text: referenceText,
            x_vector_only_mode: false,
            response_format: 'mp3',
            speed,
            max_new_tokens: 2048
        };

        const upstreamResponse = await fetch(UPSTREAM, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        const audio = Buffer.from(await upstreamResponse.arrayBuffer());

        if (!upstreamResponse.ok) {
            console.error('Qwen3-TTS error:', upstreamResponse.status, audio.toString());
            res.writeHead(502, { 'Content-Type': 'text/plain' });
            return res.end(audio);
        }

        res.writeHead(200, {
            'Content-Type': upstreamResponse.headers.get('content-type') || 'audio/mpeg',
            'Content-Length': audio.length
        });
        res.end(audio);
    } catch (error) {
        console.error(error);
        res.writeHead(500, { 'Content-Type': 'text/plain' });
        res.end(String(error));
    }
});

server.listen(PORT, '0.0.0.0', () => {
    console.log(`Galileo TTS adapter listening on port ${PORT}`);
});
