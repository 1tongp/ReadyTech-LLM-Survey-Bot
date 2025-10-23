import axios from 'axios'
const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || 'http://localhost:8000',
})

export const setAdminKey = (key) => {
  api.defaults.headers['X-API-Key'] = key
}

export default api
