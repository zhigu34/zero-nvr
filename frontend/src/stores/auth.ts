import { defineStore } from "pinia"

import { ApiClientError, apiRequest, errorMessage } from "../api/client"

export interface AuthUser {
  id: string
  username: string
  display_name: string
  email: string | null
  roles: string[]
  permissions: string[]
}

interface SetupStatus {
  requires_initial_admin: boolean
}

interface LoginInput {
  username: string
  password: string
}

interface InitialAdministratorInput {
  username: string
  display_name: string
  email: string | null
  password: string
}

export const useAuthStore = defineStore("auth", {
  state: () => ({
    initialized: false,
    setupRequired: false,
    user: null as AuthUser | null,
    bootstrapError: null as string | null
  }),

  actions: {
    hasPermission(permission: string): boolean {
      return this.user?.permissions.includes(permission) ?? false
    },

    async bootstrap(force = false): Promise<void> {
      if (this.initialized && !force) return

      this.bootstrapError = null
      try {
        const status = await apiRequest<SetupStatus>("/setup/status")
        this.setupRequired = status.requires_initial_admin

        if (this.setupRequired) {
          this.user = null
          return
        }

        try {
          this.user = await apiRequest<AuthUser>("/auth/me")
        } catch (error) {
          if (error instanceof ApiClientError && error.status === 401) {
            this.user = null
          } else {
            throw error
          }
        }
      } catch (error) {
        this.user = null
        this.bootstrapError = errorMessage(error)
      } finally {
        this.initialized = true
      }
    },

    async login(input: LoginInput): Promise<void> {
      this.user = await apiRequest<AuthUser>("/auth/login", {
        method: "POST",
        json: input
      })
      this.setupRequired = false
    },

    async createInitialAdministrator(input: InitialAdministratorInput): Promise<void> {
      await apiRequest<AuthUser>("/setup/administrator", {
        method: "POST",
        json: input
      })
      this.setupRequired = false
      this.user = null
    },

    async changePassword(input: {
      current_password: string
      new_password: string
    }): Promise<void> {
      this.user = await apiRequest<AuthUser>(
        "/auth/password/change",
        {
          method: "POST",
          json: input
        }
      )
    },

    async logout(): Promise<void> {
      try {
        await apiRequest<void>("/auth/logout", { method: "POST" })
      } finally {
        this.user = null
      }
    }
  }
})
