# PCM chunk routing between WebRTC and Gemini

#---------------audio-bridge------------------
"""
This will take the inboud audio track from the peer connection and streams PCM chunks to the
Gemini live API session. It also recieves Gemini's audio response and pushes it back through
an outbound audio track on the peer connection. It should be a tight async loop with no blocking
calls
"""




#--------------------signaling.py--------------
"""
This will handle the only the WebRTC handshake. It receives the SDP(session description protocol) offer from the frontend,
creates a peer connection via the webrct_client, and returns the SDP answer. It should
also expose an ICE candidate exchange endpoint. This file should have awareness of Gemini or AI. it should be pure WebRTC Plumbing
"""


#---------------webrct_client-------------------------------
"""
This should be the main interface to the WebRTC peer connection. The server-side peer. It 
owns the RTCPeerConnection instance and rewires everything together. It recieves the track from the frontend, hands the audio track to the audio_bridge, hands the video tracks off to the frame_sampler
and opens the data channel. It also holds the sessionContenxt(Job listing, Candidate ID) 
so every component downstream has the right context
 """


#---------------------frame_sampler----------------------
"""
this will run two independent async loops - one for the camera track one for the screen share track.
each loop will pull a frame at a set interval, encode it as JPEG and put it on a queue that the Agent can consume. Interval should be configurable per session(depending on the kind of interview, e.g technical interviews will require more screen samples than say, soft skills interview)
"""

#--------------------------data-channel-----------------------------------------
"""
This manages the bidirectional RTCDataChannel, outbound events from the backend to the frontend
will go here. Events like agent thinking, question start, interview ended and evaluation scores will go here.
Inbound events will also go through here. For instance, the candidate asking clarifying questions or pressing start screen share will come through here.
"""

"""
The whole Idea is that this realtime infra knows nothing about the domain logic and is just responsible for moving data. The agents consume from the queues/bridges that the infra exposes and
pushes responses back through them
"""