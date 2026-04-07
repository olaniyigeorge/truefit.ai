# Truefit.ai - Project Story

## Inspiration

The idea for Truefit.ai grew out of personal frustration. During previous roles, time that could have gone toward building meaningful software was instead consumed by interview panels and impromptu calls with HR teams. Then, during months of job hunting, a more troubling pattern emerged - candidates with objectively weaker skills were consistently getting hired over stronger ones.

After careful study, a few root causes stood out: bias in the interview process, inconsistent evaluation standards, and the sheer inefficiency of manual screening at scale. These weren't just inconveniences - they were quietly eroding team productivity and fairness across the industry.

The earliest version of this idea dates back to 2024, long before live multimodal models were viable. The first attempt involved piping audio through Deepgram for transcription, then passing the resulting text to Gemini Flash 2.0 for evaluation. It worked, but it was a workaround - not a real solution. The emergence of the Gemini Live API changed everything.

## What It Does

Truefit.ai automates the most time-intensive part of hiring: the interview itself.

Rather than pre-filtering candidates based on easily falsifiable documents like resumes, Truefit interviews everyone who applies - at scale, without bias. Candidates can also spin up practice interview sessions with the agent to prepare (in which case no HR member joins), while real sessions give HR teams the option to observe live if the conversation warrants it.

TrueFit runs AI-powered voice interviews that screen candidates, generate structured evaluations, and surface the right hires - so your team focuses on decisions, not scheduling.

## How We Built It

The architecture follows Gemini's recommended server-to-server integration pattern:

```
React Client -> WebSocket -> Python Backend -> WebSocket -> Gemini Live API
```

The React frontend connects to the Python backend via WebSocket to:

- Initiate the interview session
- Set up a WebRTC connection for real-time audio/video
- Manage connection lifecycle and interrupts during the interview

The backend wraps the Gemini Live agent with three key layers:

| Layer | Responsibility |
|-------|-----------------|
| Prompts | Guide the agent's conversational style and interview structure |
| Tools | Read candidate applications, record conversation turns, flag interrupts, persist answers |
| Audio Bridge | Resample audio between WebRTC's format and Gemini Live's required modality |

The flow works like this: when a candidate clicks Start Interview, a WebSocket connection opens to initiate the session and inject interview context into the agent via `sendContentContext`. That connection stays open for session management, while audio chunks (and optionally camera/screen frames) travel over WebRTC to the backend, which forwards them to the Gemini Live agent in real time.

## Challenges We Ran Into

- **🔊 Audio Resampling** - WebRTC and Gemini Live operate at different audio sample rates. Bridging them correctly without introducing distortion or latency required building a custom audio resampling layer - deceptively tricky to get right.

- **⚡ Interrupt Handling** - Deciding whether to build custom Voice Activity Detection (VAD) or rely on Gemini's built-in system was a real design challenge. Getting the behaviour to feel natural - neither cutting off the agent too early nor letting it run past a turn - required careful tuning.

- **🔁 Turn Boundary Detection** - Determining the exact moment a turn ends in the Gemini Live agent proved to be one of the trickiest problems. At one point, a timing bug caused the agent to repeat its greeting indefinitely at the start of every interview session, stuck in a loop without ever listening for the candidate's response.

## Accomplishments We're Proud Of

- 🚀 **First GCP deployment** - a genuine team milestone, and far less painful than expected
- 🎧 **Fixed audio quality** - resolved the resampling issue and eliminated the poor audio output coming through WebRTC
- 🔄 **CI/CD pipeline** - automated deployments to GCP; watching it come to life was one of the most satisfying moments of the build

## What We Learned

Building Truefit.ai confirmed something important: what once felt impossible is now just hard. When this idea first surfaced in 2024, the tooling simply wasn't there. The Gemini Live API changed that equation significantly.

Beyond the AI layer, the team got hands-on experience with GCP and saw how its services interconnect in ways that are genuinely easier to reason about than expected. We also developed a deep appreciation for how much engineering discipline goes into interactions that feel effortless to users.

Something as natural as talking - turn-taking, interruption, silence, tone - is extraordinarily complex once you try to model it in software. And that complexity matters: audio/video-first AI interaction may be the key to bringing AI into the lives of the large percentage of people who don't engage with it today, particularly across demographics and regions where text-first interfaces create friction.

Lower interaction barrier -> Broader AI adoption

## What's Next for Truefit.ai

The immediate priority is completing the core interview flow - getting every part of the experience working seamlessly before extending to adjacent HR functions.

The longer-term vision goes beyond interviews: Truefit evolves from an AI interviewer into something closer to a team performance layer - an agent that doesn't just assess candidates but actively helps managers measure and develop the people already on their teams.

Before that, the near-term goals are clear:

- 🏢 800 teams/companies onboarded on the first iteration
- 👤 7,500 individuals using Truefit for job hunting and interview prep
- 🔗 Seamless onboarding - integrations with popular job boards, support for pasting in job descriptions, and conversational session creation (e.g., a hiring manager simply describes the candidate they need, and Truefit spins up a tailored interview on demand)

The goal is simple: make hiring and job hunting more honest, more efficient, and more human - even when the interviewer is an AI.