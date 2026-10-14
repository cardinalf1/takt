import { createInterface } from 'readline';
import { Voz } from '@desert-ant-labs/voz';
import * as ort from 'onnxruntime-node';

let vozInstance = null;

// Never let a stray rejection take the worker down silently; report it and keep serving.
process.on('uncaughtException', (err) => {
    process.stderr.write(`[Voz Service] uncaughtException: ${err && err.stack ? err.stack : err}\n`);
});
process.on('unhandledRejection', (err) => {
    process.stderr.write(`[Voz Service] unhandledRejection: ${err && err.stack ? err.stack : err}\n`);
});

function reply(obj) {
    process.stdout.write(JSON.stringify(obj) + '\n');
}

async function init() {
    const requestedEp = process.env.VOZ_EP || 'dml';
    try {
        // Attempt DirectML GPU acceleration on Windows
        vozInstance = await Voz.load({ ort, ep: requestedEp });
        process.stderr.write(`Loaded Voz with ExecutionProvider '${requestedEp}'.\n`);
        reply({ status: 'ready', ep: requestedEp });
    } catch (err) {
        process.stderr.write(`Failed with '${requestedEp}' (${err.message}). Falling back to CPU.\n`);
        try {
            vozInstance = await Voz.load({ ort });
            reply({ status: 'ready', ep: 'cpu' });
        } catch (cpuErr) {
            reply({ status: 'error', error: cpuErr.message });
            process.exit(1);
        }
    }
}

// Requests are handled strictly one at a time, in order.
let chain = Promise.resolve();

async function handle(line) {
    if (!line.trim()) return;
    try {
        const req = JSON.parse(line);
        if (req.action === 'ping') {
            reply({ status: 'pong' });
            return;
        }

        if (req.action === 'transcribe') {
            if (!vozInstance) {
                reply({ status: 'error', error: 'Voz not loaded' });
                return;
            }
            const result = await vozInstance.transcribe(req.path);
            reply({
                status: 'ok',
                text: (result && result.text) || '',
                words: (result && result.words) || []
            });
            return;
        }

        reply({ status: 'error', error: 'Unknown action' });
    } catch (e) {
        reply({ status: 'error', error: e && e.message ? e.message : String(e) });
    }
}

const rl = createInterface({
    input: process.stdin,
    terminal: false
});

rl.on('line', (line) => {
    chain = chain.then(() => handle(line));
});

// Parent (Takt) closed our stdin or died: exit so we never linger as an orphan holding the GPU.
rl.on('close', () => process.exit(0));

init();
