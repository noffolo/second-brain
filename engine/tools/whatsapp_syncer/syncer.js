import makeWASocket, { useMultiFileAuthState, DisconnectReason, fetchLatestBaileysVersion } from '@whiskeysockets/baileys';
import QRCode from 'qrcode-terminal';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Carica impostazioni
const settingsPath = path.join(__dirname, 'settings.json');
let settings = { groups: [] };
try {
    settings = JSON.parse(fs.readFileSync(settingsPath, 'utf8'));
} catch (err) {
    console.error('Errore nel caricamento di settings.json:', err);
}

// Cartella sessione
const authDir = path.join(__dirname, 'auth_session');

function getMessageText(messageContent) {
    if (!messageContent) return '';
    
    // Unwrap viewOnce or ephemeral message if present
    if (messageContent.viewOnceMessageV2?.message) {
        messageContent = messageContent.viewOnceMessageV2.message;
    } else if (messageContent.viewOnceMessage?.message) {
        messageContent = messageContent.viewOnceMessage.message;
    } else if (messageContent.ephemeralMessage?.message) {
        messageContent = messageContent.ephemeralMessage.message;
    }
    
    if (messageContent.conversation) {
        return messageContent.conversation;
    }
    if (messageContent.extendedTextMessage?.text) {
        return messageContent.extendedTextMessage.text;
    }
    if (
        messageContent.imageMessage ||
        messageContent.videoMessage ||
        messageContent.audioMessage ||
        messageContent.documentMessage ||
        messageContent.stickerMessage
    ) {
        return '<Media omessi>';
    }
    return '';
}

async function startSock() {
    console.log('Inizializzazione sessione WhatsApp...');
    const { state, saveCreds } = await useMultiFileAuthState(authDir);
    
    const { version, isLatest } = await fetchLatestBaileysVersion();
    console.log(`Uso la versione del protocollo WA Web v${version.join('.')}, isLatest: ${isLatest}`);

    const sock = makeWASocket({
        auth: state,
        version: version,
        printQRInTerminal: false // Lo gestiamo noi manualmente per stampare messaggi chiari
    });

    sock.ev.on('connection.update', async (update) => {
        const { connection, lastDisconnect, qr } = update;
        
        if (qr) {
            console.log('\n--- SCANNA QUESTO QR CODE CON WHATSAPP ---');
            QRCode.generate(qr, { small: true });
            console.log('Vai su WhatsApp -> Dispositivi associati -> Collega un dispositivo\n');
        }
        
        if (connection === 'close') {
            const shouldReconnect = (lastDisconnect.error)?.output?.statusCode !== DisconnectReason.loggedOut;
            console.log('Connessione chiusa. Errore:', lastDisconnect.error, 'Riconnessione:', shouldReconnect);
            if (shouldReconnect) {
                setTimeout(startSock, 5000);
            } else {
                console.log('Disconnesso definitivamente. Cancella la cartella auth_session per riprovare.');
                process.exit(1);
            }
        } else if (connection === 'open') {
            console.log('Connessione WhatsApp aperta con successo!');
            
            if (process.argv.includes('--list-groups')) {
                console.log('Recupero dei gruppi in corso...');
                try {
                    const groups = await sock.groupFetchAllParticipating();
                    console.log('\n--- GRUPPI WHATSAPP DISPONIBILI ---');
                    for (const [jid, meta] of Object.entries(groups)) {
                        console.log(`[GROUP] Nome: "${meta.subject}" | ID: ${jid}`);
                    }
                    console.log('-----------------------------------\n');
                } catch (err) {
                    console.error('Errore nel recupero dei gruppi:', err);
                }
                sock.end();
                process.exit(0);
            }
        }
    });

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('messages.upsert', async (m) => {
        if (m.type !== 'notify') return;

        for (const msg of m.messages) {
            const jid = msg.key.remoteJid;
            if (!jid) continue;

            const matched = settings.groups.find(g => g.id === jid);
            if (!matched) continue;

            const messageText = getMessageText(msg.message);
            if (!messageText) continue; // Salta messaggi vuoti (es. reaction)

            // Formatta data
            const timestamp = msg.messageTimestamp.low || msg.messageTimestamp;
            const dateObj = new Date(timestamp * 1000);
            const day = String(dateObj.getDate()).padStart(2, '0');
            const month = String(dateObj.getMonth() + 1).padStart(2, '0');
            const year = String(dateObj.getFullYear()).slice(-2);
            const hours = String(dateObj.getHours()).padStart(2, '0');
            const minutes = String(dateObj.getMinutes()).padStart(2, '0');
            const dateStr = `${day}/${month}/${year}, ${hours}:${minutes}`;

            // Risolve il mittente
            const senderName = msg.key.fromMe 
                ? "Alessandro Tartaglia" 
                : (msg.pushName || (msg.key.participant ? msg.key.participant.split('@')[0] : jid.split('@')[0]));

            // Linea nel formato nativo esportato da WhatsApp
            const formattedLine = `${dateStr} - ${senderName}: ${messageText}\n`;

            // Percorso assoluto del file di destinazione (relativo alla root del vault)
            const targetPath = path.resolve(__dirname, '..', '..', '..', matched.target_file);

            try {
                // Crea la cartella se non esiste
                fs.mkdirSync(path.dirname(targetPath), { recursive: true });
                fs.appendFileSync(targetPath, formattedLine, 'utf8');
                console.log(`[Sync] Aggiunto a ${matched.name}: ${formattedLine.trim()}`);
            } catch (err) {
                console.error(`[Sync] Errore di scrittura su ${targetPath}:`, err);
            }
        }
    });
}

startSock();
