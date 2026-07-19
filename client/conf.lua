function love.conf(t)
  t.identity = "dq1_mmo"
  t.version = "11.5"
  t.console = true

  t.window.title = "Dragon Quest 1 MMO"
  t.window.width = 960
  t.window.height = 720
  t.window.resizable = true
  t.window.minwidth = 640
  t.window.minheight = 480

  t.modules.joystick = false
  t.modules.physics = false
  t.modules.video = false
end
