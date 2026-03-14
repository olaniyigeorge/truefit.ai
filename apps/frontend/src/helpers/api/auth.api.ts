import API from "@/helpers/api"

export const createSession = async (idToken: string): Promise<void> => {
    await API.post('/auth/oauth/token', { idToken: idToken, provider: 'firebase'});
};