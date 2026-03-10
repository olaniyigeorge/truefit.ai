import API from "@/helpers/api"

export const createSession = async (): Promise<void> => {
    await API.post('/auth/session');
};