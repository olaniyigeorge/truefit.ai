# Real-Time Communication Architecture - WebRTC & WebSocket Deep Dive

## Table of Contents

1. [WebSocket Architecture](#websocket-architecture)
2. [WebRTC Architecture](#webrtc-architecture)
3. [Signaling Protocol](#signaling-protocol)
4. [Media Stream Processing](#media-stream-processing)
5. [Connection Management](#connection-management)
6. [Error Handling](#error-handling)
7. [Performance Optimization](#performance-optimization)

---

## WebSocket Architecture

### Overview

WebSocket provides bidirectional real-time communication between frontend and backend for:
- Interview session state synchronization
- WebRTC signaling (offer/answer/ICE candidates)
- Real-time event streaming
- Transcript and AI response delivery
- Participant presence tracking

### Connection Lifecycle

```
Client                                  Server
   │                                       │
   ├─ ws://localhost:8000/ws/interview/{id}
   │                                       │
   ├─────────── WebSocket Handshake ─────→│
   │                                       │
   │◄──────────── 101 Switching ──────────│
   │              Protocols               │
   │                                       │
   ├─ {event: "join", data: {...}} ──────→│ add_connection()
   │                                       │ broadcast to others
   │                                       │
   │◄─ {event: "participant_joined"} ────│ notify all participants
   │                                       │
   ├─ {event: "webrtc_offer"} ───────────→│ receive_offer()
   │                                       │ process rtc_offer
   │                                       │ create_answer()
   │                                       │
   │◄─ {event: "webrtc_answer"} ─────────│ send answer
   │                                       │
   ├─ {event: "webrtc_ice_candidate"} ───→│ add_ice_candidate()
   │                                       │
   │◄─ {event: "webrtc_ice_candidate"} ──│ ice candidates
   │                                       │
   ├─ (Media streams active) ───────────→│ (speaking, listening)
   │                                       │
   │◄─ {event: "transcript"} ────────────│ real-time transcription
   │                                       │
   │◄─ {event: "agent_response"} ───────│ AI response
   │                                       │
   ├─ {event: "participant_muted"} ─────→│ broadcast status
   │                                       │
   │◄─ {event: "interview_status"} ─────│ status updates
   │                                       │
   ├─ (User closes) ────────────────────→│ disconnect()
   │                                       │ cleanup()
   │                                       │
   │                                       │
```

### Message Format

```typescript
interface WebSocketMessage {
  event: string;
  data: Record<string, any>;
  timestamp?: number;
  sender?: string;
}

// Examples
{
  "event": "join",
  "data": {
    "user_id": "550e8400-e29b-41d4-a716-446655440000",
    "participant_type": "recruiter", // or candidate, agent
    "session_id": "660e8400-e29b-41d4-a716-446655440000"
  }
}

{
  "event": "webrtc_offer",
  "data": {
    "type": "offer",
    "sdp": "v=0\r\no=...\r\n...",
    "from_user": "550e8400-e29b-41d4-a716-446655440000"
  }
}

{
  "event": "transcript",
  "data": {
    "text": "What is your experience with Python?",
    "speaker": "agent",
    "timestamp": 1710662400000
  }
}
```

### Server-Side Handler (FastAPI WebSocket)

```python
# backend/src/truefit_api/api/v1/ws/interview_websocket.py

@app.websocket("/ws/interview/{session_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    session_id: str,
    interview_service: InterviewOrchestrationService = Depends(get_orchestration)
):
    """
    WebSocket endpoint for interview real-time communication
    """
    # 1. Accept connection
    await websocket.accept()
    connection_id = str(uuid.uuid4())
    
    try:
        # 2. Join session
        await interview_service.add_connection(session_id, connection_id, websocket)
        
        # 3. Receive messages
        while True:
            # Receive JSON message
            message = await websocket.receive_json()
            event = message.get("event")
            data = message.get("data", {})
            
            # 4. Route event
            if event == "join":
                await handle_join(session_id, connection_id, data, interview_service)
            
            elif event == "webrtc_offer":
                await handle_webrtc_offer(session_id, connection_id, data, interview_service)
            
            elif event == "webrtc_answer":
                await handle_webrtc_answer(session_id, connection_id, data, interview_service)
            
            elif event == "webrtc_ice_candidate":
                await handle_ice_candidate(session_id, connection_id, data, interview_service)
            
            elif event == "participant_muted":
                await handle_mute_status(session_id, connection_id, data, interview_service)
            
            else:
                logger.warning(f"Unknown event: {event}")
    
    except WebSocketDisconnect:
        logger.info(f"Client {connection_id} disconnected")
        await interview_service.remove_connection(session_id, connection_id)
    
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.send_json({
                "event": "error",
                "data": {"message": str(e)}
            })
        except:
            pass
        finally:
            await interview_service.remove_connection(session_id, connection_id)
```

### Client-Side Handler (React/TypeScript)

```typescript
// frontend/src/helpers/websocket.ts

export class InterviewWebSocket {
  private ws: WebSocket | null = null;
  private messageHandlers: Map<string, Function> = new Map();
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;

  connect(sessionId: string, apiUrl: string = import.meta.env.VITE_PUBLIC_API_URL) {
    return new Promise((resolve, reject) => {
      try {
        const wsUrl = apiUrl.replace('http', 'ws') + `/ws/interview/${sessionId}`;
        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
          console.log('WebSocket connected');
          this.reconnectAttempts = 0;
          resolve(true);
        };

        this.ws.onmessage = (event) => {
          const message = JSON.parse(event.data);
          this.handleMessage(message);
        };

        this.ws.onerror = (error) => {
          console.error('WebSocket error:', error);
          reject(error);
        };

        this.ws.onclose = () => {
          console.log('WebSocket disconnected');
          this.attemptReconnect(sessionId, apiUrl);
        };
      } catch (error) {
        reject(error);
      }
    });
  }

  send(event: string, data: any) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({
        event,
        data,
        timestamp: Date.now()
      }));
    } else {
      console.warn('WebSocket not connected');
    }
  }

  on(event: string, handler: Function) {
    this.messageHandlers.set(event, handler);
  }

  off(event: string) {
    this.messageHandlers.delete(event);
  }

  private handleMessage(message: any) {
    const { event, data } = message;
    const handler = this.messageHandlers.get(event);
    if (handler) {
      handler(data);
    }
  }

  private attemptReconnect(sessionId: string, apiUrl: string) {
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      this.reconnectAttempts++;
      const delay = Math.pow(2, this.reconnectAttempts) * 1000;
      setTimeout(() => this.connect(sessionId, apiUrl), delay);
    }
  }

  close() {
    if (this.ws) {
      this.ws.close();
    }
  }
}
```

---

## WebRTC Architecture

### Peer Connection Setup

```
┌────────────────────────────────────────────────────────┐
│           WebRTC Peer Connection Setup                 │
└────────────────────────────────────────────────────────┘

Initiator (Candidate)              Non-Initiator (Backend)
        │                                    │
        ├─ Create RTCPeerConnection ───────→├─ Create RTCPeerConnection
        │                                    │
        ├─ Add local media ─────────────────→├─ Setup remote track
        │  (audio/video)                     │  handlers
        │                                    │
        ├─ createOffer() ────────────────────│
        │  (generate SDP)                    │
        │                                    │
        ├─ setLocalDescription ──────────────│
        │  (attach offer)                    │
        │                                    │
        ├─ Send via WebSocket offer ────────→├─ Receive offer
        │                                    │
        │                                    ├─ setRemoteDescription
        │                                    │  (process offer)
        │                                    │
        │                                    ├─ createAnswer()
        │                                    │  (generate SDP)
        │                                    │
        │                                    ├─ setLocalDescription
        │                                    │  (attach answer)
        │                                    │
        │                      Send answer ──├─ Send via WebSocket
        │◄──── Receive answer ───────────────┤
        │                                    │
        ├─ setRemoteDescription ────────────→│
        │  (process answer)                  │
        │                                    │
        │                  Collect ICE ─────→├─ Collect ICE
        │  ◄──── Bidirectional ICE ─────────│  Candidates
        │    Candidate Exchange             │
        │                                    │
        │  RTCPeerConnection established    │
        │◄─────────── DTLS ────────────────→│ DTLS Handshake
        │                                    │
        │◄─────── Media Streams ───────────→│ Encrypted Media
        │     (SRTP Encrypted)              │
        │                                    │
```

### ICE (Interactive Connectivity Establishment)

```
ICE Candidates Exchange:

Candidate: Local Address 192.168.1.100:54321
           ├─ Host candidate (mDNS, privacy)
           ├─ Server Reflexive (STUN server)
           ├─ Peer Reflexive
           └─ Relay (TURN server)

Each candidate includes:
├─ Priority
├─ Transport (udp)
├─ Foundation (unique per session)
└─ Address/Port pair

The browser tries each pair in priority order until one works.
```

### Backend WebRTC Implementation

```python
# backend/src/truefit_infra/realtime/webrtc_client.py

class WebRTCClient:
    """
    Manages WebRTC peer connection on backend
    """
    
    def __init__(self):
        self.pc = RTCPeerConnection()
        self.local_stream = None
        self.remote_stream = None
        self.session_context = None
        
    async def init_from_offer(self, offer_sdp: str):
        """Initialize from candidate offer"""
        # Get media from source (e.g., Gemini Live)
        self.local_stream = await self.get_ai_audio_stream()
        
        # Add local track to peer connection
        audio_track = self.local_stream.audio_track
        self.pc.addTrack(audio_track)
        
        # Set remote description (from candidate)
        offer = RTCSessionDescription(sdp=offer_sdp, type="offer")
        await self.pc.setRemoteDescription(offer)
        
        # Create and send answer
        answer = await self.pc.createAnswer()
        await self.pc.setLocalDescription(answer)
        
        return self.pc.localDescription.sdp
    
    async def handle_ice_candidate(self, candidate_json: str):
        """Add ICE candidate from remote peer"""
        candidate = RTCIceCandidate(**json.loads(candidate_json))
        await self.pc.addIceCandidate(candidate)
    
    async def get_ai_audio_stream(self):
        """Get audio stream from AI (Gemini Live)"""
        # Connected to Gemini Live API
        return AIAudioStream()
    
    @self.pc.on("track")
    async def on_track(track):
        """Handle incoming remote track"""
        if track.kind == "audio":
            self.remote_stream.add_track(track)
            # Process audio (transcription, etc.)
            await process_audio(track)
```

### Frontend WebRTC Implementation

```typescript
// frontend/src/components/InterviewRoom.tsx

export class InterviewRoom {
  private pc: RTCPeerConnection | null = null;
  private localStream: MediaStream | null = null;
  private ws: InterviewWebSocket;

  async initializeConnection() {
    try {
      // 1. Get local media
      this.localStream = await navigator.mediaDevices.getUserMedia({
        audio: true,
        video: {
          width: { ideal: 1280 },
          height: { ideal: 720 }
        }
      });

      // 2. Create peer connection
      this.pc = new RTCPeerConnection({
        iceServers: [
          { urls: 'stun:stun.l.google.com:19302' },
          { urls: 'stun:stun1.l.google.com:19302' }
        ]
      });

      // 3. Add local stream tracks
      this.localStream.getTracks().forEach(track => {
        this.pc!.addTrack(track, this.localStream!);
      });

      // 4. Handle remote tracks
      this.pc.ontrack = (event) => {
        console.log('Remote track received:', event.track.kind);
        this.remoteStream.addTrack(event.track);
      };

      // 5. Handle ICE candidates
      this.pc.onicecandidate = (event) => {
        if (event.candidate) {
          this.ws.send('webrtc_ice_candidate', {
            candidate: event.candidate.candidate,
            sdpMLineIndex: event.candidate.sdpMLineIndex,
            sdpMid: event.candidate.sdpMid
          });
        }
      };

      // 6. Create offer
      const offer = await this.pc.createOffer();
      await this.pc.setLocalDescription(offer);

      // 7. Send offer via WebSocket
      this.ws.send('webrtc_offer', {
        type: 'offer',
        sdp: this.pc.localDescription.sdp
      });

      // 8. Wait for answer
      this.ws.on('webrtc_answer', async (data) => {
        const answer = new RTCSessionDescription({
          type: 'answer',
          sdp: data.sdp
        });
        await this.pc!.setRemoteDescription(answer);
      });

    } catch (error) {
      console.error('Failed to initialize WebRTC:', error);
      throw error;
    }
  }

  async handleAnswer(answerSdp: string) {
    const answer = new RTCSessionDescription({
      type: 'answer',
      sdp: answerSdp
    });
    await this.pc!.setRemoteDescription(answer);
  }

  getLocalStream(): MediaStream | null {
    return this.localStream;
  }

  close() {
    if (this.localStream) {
      this.localStream.getTracks().forEach(track => track.stop());
    }
    if (this.pc) {
      this.pc.close();
    }
  }
}
```

---

## Signaling Protocol

### Event Sequence Diagram

```
Candidate                WebSocket              Backend
   │                         │                      │
   ├─ join ──────────────────→├─ broadcast ────────→ Store connection
   │                         │
   ├─ webrtc_offer ──────────→├─ forward ──────────→ Create peer connection
   │                         │    to backend      Set remote desc.
   │                         │                      Create answer
   │                         │
   │                         │◄──── webrtc_answer ──┤
   │◄───── webrtc_answer ─────┤
   │  (from broadcast)        │
   │                          │
   ├─ ice_candidate1 ────────→├────────────────────→ addIceCandidate()
   │                         │                      │
   │                         │◄─ ice_candidate1 ───┤
   │◄─ ice_candidate1 ────────┤
   │                          │
   ├─ audio frames ──────────→├────────────────────→ Process
   │  (via RTC)              │                      │ Transcribe
   │                          │                      │ Generate response
   │                          │
   │                         │◄─ transcript ────────┤
   │◄─ transcript ─────────────┤
   │
   │◄─ agent_response ─────────────────────────────┤
   │  (audio via RTC)
   │
```

### Message States

```
INITIATOR                          RESPONDER

1. Idle                            1. Idle (waiting for offer)

2. offer_created                   
   └─ createOffer()                

3. offer_sent                      2. offer_received
   └─ send offer                      └─ setRemoteDescription(offer)
                                       └─ createAnswer()

4. answer_received                 3. answer_sent
   └─ setRemoteDescription(ans)       └─ send answer

5. connected                       4. connected
   └─ media flowing                   └─ media flowing
```

---

## Media Stream Processing

### Audio Processing Pipeline

```
Candidate Audio
        ↓
    WebRTC Audio Track
        ↓
    aiortc (local RTC library)
        ↓
    Audio Buffer (PCM 16kHz)
        ↓
    Gemini Live API Stream
        ↓
    AI Processing:
    ├─ Speech recognition
    ├─ Context understanding
    ├─ Response generation
    └─ Speech synthesis
        ↓
    Audio Output Stream
        ↓
    WebRTC Audio Track (Backend Engine)
        ↓
    Candidate Hears Response
```

### Gemini Live Integration

```python
# backend/src/truefit_infra/llm/gemini_live.py

class GeminiLiveAdapter:
    """
    Adapter for Google Gemini Live API
    """
    
    async def process_audio_stream(self, audio_track):
        """
        Process live audio stream with Gemini
        """
        async with genai.live.connect() as connection:
            
            # Send system prompt
            await connection.send(Content(
                parts=[Part(text=self.system_prompt)]
            ))
            
            # Process audio frames
            async for frame in audio_track:
                # Convert to bytes
                audio_bytes = frame.to_ndarray().tobytes()
                
                # Send to Gemini
                await connection.send(Content(
                    parts=[Part(data=audio_bytes)]
                ))
                
                # Receive response
                async for response in connection:
                    if response.parts:
                        # Handle text or audio response
                        for part in response.parts:
                            if hasattr(part, 'text'):
                                # Transcript
                                yield TranscriptEvent(text=part.text)
                            elif hasattr(part, 'data'):
                                # Audio response
                                yield AudioEvent(data=part.data)
```

---

## Connection Management

### Connection State Tracking

```python
class SessionContext:
    """Track connection states"""
    
    def __init__(self, session_id: UUID):
        self.session_id = session_id
        self.connections: Dict[str, ConnectionContext] = {}
        self.pc: Optional[RTCPeerConnection] = None
        self.state = SessionState.CREATED
    
    class ConnectionState(Enum):
        CONNECTING = "connecting"
        CONNECTED = "connected"
        DISCONNECTED = "disconnected"
        FAILED = "failed"
    
    async def add_connection(self, conn_id: str, websocket: WebSocket):
        self.connections[conn_id] = ConnectionContext(
            id=conn_id,
            websocket=websocket,
            state=ConnectionState.CONNECTING
        )
    
    async def remove_connection(self, conn_id: str):
        if conn_id in self.connections:
            del self.connections[conn_id]
            
            # Notify others
            await self.broadcast({
                "event": "participant_left",
                "data": {"connection_id": conn_id}
            })
```

### Reconnection Logic

```typescript
// Frontend reconnection strategy

const MAX_RECONNECT_ATTEMPTS = 5;
const BASE_RETRY_DELAY = 1000; // 1 second

async function reconnect() {
  let attempt = 0;
  
  while (attempt < MAX_RECONNECT_ATTEMPTS) {
    try {
      await ws.connect(sessionId);
      
      // Restore connection
      await restoreRTCConnection();
      return true;
      
    } catch (error) {
      attempt++;
      const delay = BASE_RETRY_DELAY * Math.pow(2, attempt);
      console.log(`Reconnect attempt ${attempt} failed, retrying in ${delay}ms`);
      await new Promise(r => setTimeout(r, delay));
    }
  }
  
  // Give up
  handleConnectionLoss();
  return false;
}
```

---

## Error Handling

### Common Errors

```javascript
// WebRTC Errors

1. NotAllowedError
   ├─ Cause: User denied permission for media
   └─ Fix: Check browser console, ensure permissions granted

2. NotFoundError
   ├─ Cause: No microphone/camera found
   └─ Fix: Attach devices, check device permissions

3. NetworkError
   ├─ Cause: Network connectivity issue
   └─ Fix: Check internet connection, firewall rules

4. RTCError: setRemoteDescription() called during ICE gathering
   ├─ Cause: Race condition in signaling
   └─ Fix: Queue descriptions, handle properly

5. ICE Connection Failed
   ├─ Cause: No viable connection path between peers
   └─ Fix: Open firewall, use TURN server

// WebSocket Errors

1. Connection refused
   ├─ Cause: Backend not running
   └─ Fix: Start backend server

2. 403 Forbidden
   ├─ Cause: Authentication failed
   └─ Fix: Check JWT token validity

3. Timeout
   ├─ Cause: Network latency
   └─ Fix: Increase timeout threshold, check network
```

### Error Recovery

```python
# Backend

@app.websocket("/ws/interview/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    try:
        await websocket.accept()
        
        try:
            session = await interview_service.get_session(session_id)
        except SessionNotFound:
            await websocket.send_json({
                "event": "error",
                "data": {"code": 404, "message": "Session not found"}
            })
            await websocket.close(code=4000)
            return
        
        try:
            # Main loop
            while True:
                message = await websocket.receive_json()
                await process_message(message)
        
        except WebSocketDisconnect:
            await cleanup_connection(session_id, connection_id)
        
        except Exception as e:
            logger.error(f"Error in WebSocket: {e}", exc_info=True)
            await websocket.send_json({
                "event": "error",
                "data": {"message": "Internal server error"}
            })
    
    except Exception as e:
        logger.error(f"WebSocket fatal error: {e}", exc_info=True)
```

---

## Performance Optimization

### Optimization Strategies

```python
# 1. Connection pooling
class WebSocketConnectionPool:
    def __init__(self, max_size=1000):
        self.pool: Dict[str, WebSocket] = {}
        self.max_size = max_size
    
    async def broadcast(self, event: str, data: dict):
        """Send to all connections efficiently"""
        tasks = [
            ws.send_json({"event": event, "data": data})
            for ws in self.pool.values()
            if ws.client_state == WebSocketState.CONNECTED
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

# 2. Message batching
class MessageBatcher:
    def __init__(self, batch_size=10, timeout=0.1):
        self.batch = []
        self.batch_size = batch_size
        self.timeout = timeout
    
    async def add(self, message):
        self.batch.append(message)
        if len(self.batch) >= self.batch_size:
            await self.flush()

# 3. Selective broadcasting
async def broadcast_transcript(session_id: str, text: str):
    """Only send to recruiter/observer connections"""
    session = get_session(session_id)
    for conn_id, context in session.connections.items():
        if context.participant_type == "recruiter":
            await send_message(conn_id, {
                "event": "transcript",
                "data": {"text": text}
            })

# 4. Compression for large payloads
import zlib

async def send_compressed(connection: WebSocket, data: dict):
    json_str = json.dumps(data)
    compressed = zlib.compress(json_str.encode())
    await connection.send_bytes(compressed)
```

### Monitoring & Metrics

```python
class PerformanceMonitor:
    """Monitor WebRTC and WebSocket performance"""
    
    async def track_connection(self, pc: RTCPeerConnection, session_id: str):
        while True:
            stats = await pc.getStats()
            
            for report in stats:
                if report.type == 'inbound-rtp':
                    logger.info(f"Inbound: {report.bytesReceived} bytes, "
                               f"packets lost: {report.packetsLost}")
                
                elif report.type == 'outbound-rtp':
                    logger.info(f"Outbound: {report.bytesSent} bytes, "
                               f"frame rate: {report.framesPerSecond}")
                
                elif report.type == 'candidate-pair':
                    if report.state == 'succeeded':
                        logger.info(f"Connection RTT: {report.currentRoundTripTime}s")
            
            await asyncio.sleep(5)  # Every 5 seconds
```

---

**Last Updated**: March 16, 2026
**Version**: 1.0
