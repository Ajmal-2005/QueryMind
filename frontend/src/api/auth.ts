import { api } from './client'
import type { TokenResponse, User } from './types'

export async function login(email: string, password: string): Promise<TokenResponse> {
  const { data } = await api.post<TokenResponse>('/auth/login', { email, password })
  return data
}

export async function register(
  email: string,
  password: string,
  fullName: string,
): Promise<TokenResponse> {
  const { data } = await api.post<TokenResponse>('/auth/register', {
    email,
    password,
    full_name: fullName,
  })
  return data
}

export async function fetchMe(): Promise<User> {
  const { data } = await api.get<User>('/auth/me')
  return data
}
