--!nocheck
-- Generado por ForgeMesh (motor de animación v2). ModuleScript.
-- Piezas (MeshPart) en: ReplicatedStorage > ForgeParts > __MODELO__  (+ carpeta opcional "Extras" con pisos/colisiones)
--
-- USO desde un LocalScript (mejor rendimiento):
--   local h = require(ruta.A.Este.Modulo).Build(CFrame.new(0, 10, 0))
--   h.SetCFrame(cf)                      -- mover el modelo entero (ej. el tren sobre los rieles)
--   h.Play("rugido")                     -- reproducir un clip (o: h.Model:SetAttribute("Clip", "rugido"))
--   h.Stop("rugido")                     -- parar un clip en bucle
--   h.Model:SetAttribute("Velocidad", 40)   -- studs/s: las piezas "girar" con vel=1/radio dan el giro exacto de rueda
--   h.Model:SetAttribute("Intensidad", 1)   -- fuerza de las piezas "vibrar"
--   h.Model:SetAttribute("parte_03_abierto", true)  -- control manual de una "bisagra" (nil = automático)
-- Capas: las animaciones base (idle, ruedas, luces) siguen corriendo MIENTRAS suena un clip; el clip se suma encima.

local RunService = game:GetService("RunService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local Debris = game:GetService("Debris")

local MODELO = "__MODELO__"
local COLISION = false                       -- true si los jugadores deben chocar con las piezas animadas
local ESPEJO = Vector3.new(1, 1, 1)          -- si las piezas quedan reflejadas pon (-1,1,1) o (1,1,-1)
local COLOR_MAP = "__COLOR__"                -- IDs de textura compartidos (rbxassetid://...) = menos RAM
local METAL_MAP = "__METAL__"
local ROUGH_MAP = "__ROUGH__"

local PARTES = {
__FILAS__
}

local CLIPS = {
__CLIPS__
}

----------------------------------------------------------------------------------------------------
-- Utilidades
----------------------------------------------------------------------------------------------------
local function about(pivot, rot)
	return CFrame.new(pivot) * rot * CFrame.new(-pivot)
end

local function newSpring()
	return { p = 0, v = 0 }
end

local function stepSpring(s, target, freq, damp, dt)
	local w = 2 * math.pi * freq
	local acc = w * w * (target - s.p) - 2 * damp * w * s.v
	s.v = s.v + acc * dt
	s.p = s.p + s.v * dt
	return s.p
end

local function easeOutBounce(x)
	local n1, d1 = 7.5625, 2.75
	if x < 1 / d1 then
		return n1 * x * x
	elseif x < 2 / d1 then
		x = x - 1.5 / d1
		return n1 * x * x + 0.75
	elseif x < 2.5 / d1 then
		x = x - 2.25 / d1
		return n1 * x * x + 0.9375
	end
	x = x - 2.625 / d1
	return n1 * x * x + 0.984375
end

local EASE = {
	linear = function(x) return x end,
	cubic = function(x)
		if x < 0.5 then return 4 * x * x * x end
		local q = -2 * x + 2
		return 1 - (q * q * q) / 2
	end,
	cubicout = function(x) local q = 1 - x return 1 - q * q * q end,
	cubicin = function(x) return x * x * x end,
	back = function(x)
		local c1, c3 = 1.70158, 2.70158
		local q = x - 1
		return 1 + c3 * q * q * q + c1 * q * q
	end,
	backin = function(x)
		local c1, c3 = 1.70158, 2.70158
		return c3 * x * x * x - c1 * x * x
	end,
	elastic = function(x)
		if x <= 0 then return 0 end
		if x >= 1 then return 1 end
		return 2 ^ (-10 * x) * math.sin((x * 10 - 0.75) * (2 * math.pi / 3)) + 1
	end,
	bounce = easeOutBounce,
	sine = function(x) return -(math.cos(math.pi * x) - 1) / 2 end,
	expo = function(x)
		if x >= 1 then return 1 end
		return 1 - 2 ^ (-10 * x)
	end,
	hold = function(x) if x >= 1 then return 1 end return 0 end,
}

-- valor de una curva de keyframes {t, valor, easing}; el easing de cada key describe el tramo que LLEGA a esa key
local function sample(keys, t)
	local n = #keys
	if t <= keys[1][1] then return keys[1][2] end
	if t >= keys[n][1] then return keys[n][2] end
	for i = 1, n - 1 do
		local a, b = keys[i], keys[i + 1]
		if t < b[1] then
			local span = b[1] - a[1]
			local x = 1
			if span > 0 then x = (t - a[1]) / span end
			local f = (EASE[b[3]] or EASE.cubic)(x)
			return a[2] + (b[2] - a[2]) * f
		end
	end
	return keys[n][2]
end

----------------------------------------------------------------------------------------------------
-- Cámara (global): sacudida y golpe de FOV con caída exponencial
----------------------------------------------------------------------------------------------------
local camAmp, camFov, camBase, camBound = 0, 0, nil, false

local function asegurarCamara()
	if camBound or not RunService:IsClient() then return end
	camBound = true
	RunService:BindToRenderStep("ForgeCamFX", Enum.RenderPriority.Camera.Value + 1, function(dt)
		local cam = workspace.CurrentCamera
		if not cam then return end
		if camAmp > 0.002 then
			local n = os.clock() * 28
			local x, y, z = math.noise(n, 1.1, 0), math.noise(2.2, n, 0), math.noise(0, 3.3, n)
			cam.CFrame = cam.CFrame * CFrame.new(x * camAmp, y * camAmp, 0) * CFrame.Angles(0, 0, z * camAmp * 0.012)
			camAmp = camAmp * math.exp(-5 * dt)
		else
			camAmp = 0
		end
		if camFov > 0.02 then
			if not camBase then camBase = cam.FieldOfView end
			cam.FieldOfView = camBase + camFov
			camFov = camFov * math.exp(-9 * dt)
		elseif camBase then
			cam.FieldOfView = camBase
			camBase = nil
			camFov = 0
		end
	end)
end

----------------------------------------------------------------------------------------------------
-- Capas procedurales (idle, ruedas, luces...)
----------------------------------------------------------------------------------------------------
local function capaCF(cap, t, dt, model)
	local d = cap.d
	local k = d.anim
	if k == "girar" then
		local mult = model:GetAttribute("Velocidad")
		if mult == nil then mult = 1 end
		cap.ang = cap.ang + d.vel * mult * dt
		return about(d.pivot, CFrame.fromAxisAngle(d.eje, cap.ang))

	elseif k == "bisagra" then
		local manual = model:GetAttribute(cap.name .. "_abierto")
		local abierto
		if manual ~= nil then
			abierto = manual
		else
			abierto = ((t / d.periodo) % 1) > 0.5
		end
		if abierto and not cap.prev then cap.ant = 0.14 end
		cap.prev = abierto
		local target = 0
		if abierto then
			if cap.ant > 0 then target = -0.18 else target = 1 end
		end
		cap.ant = math.max(0, cap.ant - dt)
		local freq, damp = 2.2, 0.42
		if not abierto then freq, damp = 3.6, 0.75 end
		local f = stepSpring(cap.spring, target, freq, damp, dt)
		return about(d.pivot, CFrame.fromAxisAngle(d.eje, math.rad(d.ang) * f))

	elseif k == "vibrar" then
		local inten = model:GetAttribute("Intensidad")
		if inten == nil then inten = 1 end
		local n = t * d.vel
		local v = Vector3.new(math.noise(n, cap.seed, 0), math.noise(cap.seed, n, 7.1), math.noise(n, 3.3, cap.seed))
		return CFrame.new(v * 2 * d.fuerza * inten)

	elseif k == "flotar" then
		local y = math.sin(t * d.vel + cap.seed) + 0.3 * math.sin(t * d.vel * 2.3 + cap.seed * 1.7)
		return CFrame.new(0, y * d.altura, 0)

	elseif k == "balanceo" then
		local a = math.rad(d.ang) * (math.sin(t * d.vel + cap.seed) + 0.35 * math.noise(t * 0.7, cap.seed, 0))
		return about(d.pivot, CFrame.fromAxisAngle(d.eje, a))

	elseif k == "pulso" then
		if not cap.light then
			local l = cap.part:FindFirstChildOfClass("PointLight") or Instance.new("PointLight")
			l.Color = d.color
			l.Range = d.rango
			l.Parent = cap.part
			cap.light = l
		end
		local s = 0.5 + 0.5 * math.sin(t * d.vel * math.pi * 2 + cap.seed)
		local flick = 1 + 0.08 * math.noise(t * 9, cap.seed, 0)
		cap.light.Brightness = (d.min + (d.max - d.min) * s) * flick
	end
	return CFrame.identity
end

----------------------------------------------------------------------------------------------------
local Module = {}

function Module.Build(cf)
	local carpeta = ReplicatedStorage:WaitForChild("ForgeParts"):WaitForChild(MODELO)
	local model = Instance.new("Model")
	model.Name = MODELO
	local items, byName = {}, {}
	for i, d in ipairs(PARTES) do
		local src = carpeta:FindFirstChild(d.name)
		if src and not src:IsA("BasePart") then src = src:FindFirstChildWhichIsA("MeshPart", true) end
		if not src then
			warn("ForgeMesh: falta la pieza " .. d.name)
		else
			local p = src:Clone()
			p.Anchored = true
			p.CanCollide = COLISION
			p.CanTouch = COLISION
			p.CanQuery = COLISION
			if COLOR_MAP ~= "" then
				local sa = p:FindFirstChildOfClass("SurfaceAppearance") or Instance.new("SurfaceAppearance")
				sa.ColorMap = COLOR_MAP
				if METAL_MAP ~= "" then sa.MetalnessMap = METAL_MAP end
				if ROUGH_MAP ~= "" then sa.RoughnessMap = ROUGH_MAP end
				sa.Parent = p
			end
			p.Parent = model
			local it = { part = p, d = d, name = d.name, offset = d.offset * ESPEJO, capas = {} }
			for j, c in ipairs(d.capas) do
				table.insert(it.capas, {
					d = c, part = p, name = d.name, seed = i * 13.37 + j * 3.1,
					spring = newSpring(), ang = 0, ant = 0, prev = false,
				})
			end
			table.insert(items, it)
			byName[d.name] = it
		end
	end
	assert(#items > 0, "ForgeMesh: no se encontró ninguna pieza en ForgeParts." .. MODELO)
	model.PrimaryPart = items[1].part

	local extras = {}
	local exf = carpeta:FindFirstChild("Extras")
	if exf then
		for _, e in ipairs(exf:GetChildren()) do
			if e:IsA("BasePart") then
				local c = e:Clone()
				c.Anchored = true
				c.Parent = model
				table.insert(extras, { part = c, cf = e.CFrame })
			end
		end
	end
	model.Parent = workspace

	local plist = {}
	for _, it in ipairs(items) do table.insert(plist, it.part) end
	for _, x in ipairs(extras) do table.insert(plist, x.part) end
	local clist = table.create(#plist, CFrame.identity)

	-- índice de pistas por pieza
	for _, c in pairs(CLIPS) do
		if not c.porParte then
			c.porParte = {}
			for _, tr in ipairs(c.tracks) do
				if not c.porParte[tr.parte] then c.porParte[tr.parte] = {} end
				table.insert(c.porParte[tr.parte], tr)
			end
		end
	end

	----------------------------------------------------------------------------------------------
	-- Efectos sincronizados con los clips
	----------------------------------------------------------------------------------------------
	local flashes = {}
	local congelar = 0

	local function flash(nombre, fuerza)
		local it = byName[nombre]
		if not it then return end
		local l = it.part:FindFirstChild("ForgeFlash")
		if not l then
			l = Instance.new("PointLight")
			l.Name = "ForgeFlash"
			l.Range = 18
			l.Color = Color3.fromRGB(255, 190, 120)
			l.Brightness = 0
			l.Parent = it.part
		end
		l.Brightness = fuerza
		flashes[l] = true
	end

	local function sonido(id, vol)
		local s = Instance.new("Sound")
		s.SoundId = id
		s.Volume = vol
		s.RollOffMaxDistance = 200
		s.PlaybackSpeed = 0.95 + math.random() * 0.1
		s.Parent = items[1].part
		s:Play()
		Debris:AddItem(s, 8)
	end

	local function emitir(nombre, n)
		local it = byName[nombre]
		if not it then return end
		for _, d in ipairs(it.part:GetDescendants()) do
			if d:IsA("ParticleEmitter") then d:Emit(n) end
		end
	end

	local function dispararFx(fx)
		local k = 1
		local cam = workspace.CurrentCamera
		if cam and RunService:IsClient() then
			local dist = (cam.CFrame.Position - items[1].part.Position).Magnitude
			k = math.clamp(1 - dist / (fx.rango or 140), 0, 1)
		end
		if fx.shake and fx.shake > 0 then
			asegurarCamara()
			camAmp = math.min(camAmp + fx.shake * k, 3)
		end
		if fx.fov and fx.fov > 0 then
			asegurarCamara()
			camFov = math.min(camFov + fx.fov * k, 14)
		end
		if fx.hitstop and fx.hitstop > 0 then congelar = math.max(congelar, fx.hitstop) end
		if fx.flash then flash(fx.flash, fx.flashfuerza or 3) end
		if fx.sound and fx.sound ~= "" then sonido(fx.sound, fx.vol or 1) end
		if fx.emit then
			for _, nombre in ipairs(fx.emit) do emitir(nombre, fx.cantidad or 20) end
		end
	end

	----------------------------------------------------------------------------------------------
	-- Reproductor de clips (capas aditivas con mezcla de entrada y salida)
	----------------------------------------------------------------------------------------------
	local activos = {}

	local function Play(nombre)
		local c = CLIPS[nombre]
		if not c then
			warn("ForgeMesh: no existe el clip " .. tostring(nombre))
			return
		end
		for i, a in ipairs(activos) do
			if a.nombre == nombre then
				table.remove(activos, i)
				break
			end
		end
		table.insert(activos, { nombre = nombre, c = c, t = 0, w = 0, parar = false, salida = 0 })
		-- los fx con t = 0 se disparan en el primer avance
	end

	local function Stop(nombre)
		for _, a in ipairs(activos) do
			if a.nombre == nombre then a.parar = true end
		end
	end

	local function avanzar(dt)
		local dtc = dt
		if congelar > 0 then
			congelar = congelar - dt
			dtc = 0
		end
		for i = #activos, 1, -1 do
			local a = activos[i]
			local c = a.c
			local prev = a.t
			if a.nuevo == nil then prev = -1 a.nuevo = false end
			a.t = a.t + dtc
			if c.loop and not a.parar and a.t >= c.dur then
				a.t = a.t - c.dur
				prev = -1
			end
			local m = c.mezcla
			local w = 1
			if m > 0 then
				w = math.min(1, a.t / m)
				if c.loop then
					if a.parar then
						a.salida = a.salida + dtc
						w = w * math.max(0, 1 - a.salida / m)
					end
				else
					w = w * math.min(1, math.max(0, (c.dur - a.t) / m))
				end
			end
			a.w = w
			if c.fx then
				for _, fx in ipairs(c.fx) do
					if prev < fx.t and a.t >= fx.t then dispararFx(fx) end
				end
			end
			local fin = false
			if c.loop then
				if a.parar and m <= 0 then fin = true end
				if a.parar and a.salida >= m and m > 0 then fin = true end
			elseif a.t >= c.dur then
				fin = true
			end
			if fin then table.remove(activos, i) end
		end
	end

	local function clipCF(it)
		local r = CFrame.identity
		for _, a in ipairs(activos) do
			local lista = a.c.porParte[it.name]
			if lista and a.w > 0 then
				for _, tr in ipairs(lista) do
					local v = sample(tr.keys, a.t) * a.w
					if tr.tipo == "rot" then
						r = r * about(tr.pivot, CFrame.fromAxisAngle(tr.eje, math.rad(v)))
					else
						r = r * CFrame.new(tr.eje * v)
					end
				end
			end
		end
		return r
	end

	local function capasCF(it, t, dt)
		local r = CFrame.identity
		for _, cap in ipairs(it.capas) do
			r = r * capaCF(cap, t, dt, model)
		end
		return r
	end

	local attrConn = model:GetAttributeChangedSignal("Clip"):Connect(function()
		local v = model:GetAttribute("Clip")
		if type(v) == "string" and v ~= "" then
			Play(v)
			model:SetAttribute("Clip", "")
		end
	end)

	local rootBase = cf
	local t0 = os.clock()
	local evento = RunService:IsClient() and RunService.RenderStepped or RunService.Heartbeat
	local conn = evento:Connect(function(dt)
		dt = math.min(dt, 1 / 30)
		local t = os.clock() - t0
		avanzar(dt)
		for l, _ in pairs(flashes) do
			l.Brightness = l.Brightness * math.exp(-6 * dt)
			if l.Brightness < 0.02 then
				l.Brightness = 0
				flashes[l] = nil
			end
		end
		local globalCF = rootBase * capasCF(items[1], t, dt) * clipCF(items[1])
		clist[1] = globalCF
		for i = 2, #items do
			local it = items[i]
			clist[i] = globalCF * CFrame.new(it.offset) * capasCF(it, t, dt) * clipCF(it)
		end
		for j, x in ipairs(extras) do
			clist[#items + j] = globalCF * x.cf
		end
		workspace:BulkMoveTo(plist, clist, Enum.BulkMoveMode.FireCFrameChanged)
	end)

	return {
		Model = model,
		Play = Play,
		Stop = Stop,
		SetCFrame = function(c) rootBase = c end,
		Destroy = function()
			conn:Disconnect()
			attrConn:Disconnect()
			model:Destroy()
		end,
	}
end

return Module
