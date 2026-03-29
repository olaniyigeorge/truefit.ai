import API from "@/helpers/api"


export type IceServer = {
    urls: string | string[]
    username?: string
    credential?: string
}

export type TurnCredentials = {
    ice_servers: IceServer[]
}

type RawIceServer = IceServer & {
    credentials?: string
}


export const turnApi = {
    getCredentials: async (): Promise<TurnCredentials> => {
        const res = await API.get("api/v1/turn/credentials")
        const rawIceServers = Array.isArray(res.data?.ice_servers) ? (res.data.ice_servers as RawIceServer[]) : []

        const ice_servers = rawIceServers.flatMap((server) => {
            const urls = Array.isArray(server.urls) ? server.urls : [server.urls]
            const credential = server.credential ?? server.credentials

            const hasTurnUrl = urls.some((url) => typeof url === "string" && /^(turn|turns):/i.test(url))
            if (hasTurnUrl && (!server.username || !credential)) {
                console.warn("Skipping invalid TURN server config because username/credential is missing", server)
                return []
            }

            return [{
                urls: Array.isArray(server.urls) ? server.urls : server.urls,
                username: server.username,
                credential,
            }]
        })

        return { ice_servers }
    }
}
