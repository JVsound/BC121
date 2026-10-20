% BC121 Configuration C: SPL of the loudspeaker system (JVsound) from the Ansys Mechanical exports
sourceVoltage = 28.3; % RMS voltage of the amplifier in [V]
diaphragmVelocity = 1e-3; % Velocity imposed on the diaphragm in the FEA model in [m/s]
folder = fileparts(mfilename("fullpath"));

readExport = @(name) readmatrix(fullfile(folder,name),FileType="text",NumHeaderLines=1);
front = readExport("Frequency Response Front.txt");
rear = readExport("Frequency Response Rear.txt");
mesh1m = readExport("Frequency Response Mic1m.txt");
frequency = front(:,1);
assert(isequal(size(rear,1),numel(frequency),size(mesh1m,1)),"The exports have other frequencies.")
toPa = @(x) (x(:,4) + 1i*x(:,5))*1e6; % Mechanical exports MPa
asData = @(p) struct(Frequency=frequency.',Pressure=p(:).');
farField = readFarField(folder);

sys = lspsys;
sys.SourceVoltage = sourceVoltage;
sys.Enclosure = comp.FeaEnclosure;
sys.Enclosure.PressureFront = asData(toPa(front));
sys.Enclosure.PressureRear = asData(toPa(rear));
sys.Enclosure.DiaphragmVelocity = diaphragmVelocity;
sys.Enclosure.Driver = comp.Driver;
sys.Enclosure.Driver.Re = 6;
sys.Enclosure.Driver.Le = 2.2e-3;
sys.Enclosure.Driver.Qes = 0.38;
sys.Enclosure.Driver.Qms = 6.4;
sys.Enclosure.Driver.Fs = 32;
sys.Enclosure.Driver.Sd = 1680e-4;
sys.Enclosure.Driver.Vas = 200e-3;
sys.Enclosure.Driver.Znom = 8;
sys.Enclosure.Driver.Zmin = 7;
sys.Enclosure.Driver.Pnom = 2000;
sys.Enclosure.Driver.Xvar = 16e-3;
sys.Frequency = sys.Enclosure.Frequency;

names = ["Mic 1 m" "Mic " + replace([farField.Name],"Mic","")];
pressures = [{toPa(mesh1m)} arrayfun(@(f) f.Pressure.',farField,UniformOutput=false)];
level = zeros(numel(frequency),numel(names));
levelMax = level;
for k = 1:numel(names)
    sys.Enclosure.PressureFarField = asData(pressures{k});
    res = sys.createResult;
    level(:,k) = res.SoundPressureLevel(:);
    impedance = res.ElectricalImpedance(:); % does not depend on the microphone
    maxLevel = res.splMax;
    levelMax(:,k) = maxLevel(:); % highest level that the excursion and power limit of the driver allow
end

fig = figure(Name="Configuration C",Position=[100 100 1000 500]);
semilogx(frequency,level,LineWidth=1.5), grid on
xlabel("Frequency (Hz)"), ylabel("SPL (dB re 20 " + char(181) + "Pa)")
title("Configuration C at " + sourceVoltage + " V RMS")
legend(names,Location="best")
exportgraphics(fig,fullfile(folder,"ConfigurationC.png"),Resolution=150)
[peak,index] = max(level);
disp(table(names.',peak.',frequency(index),VariableNames=["Microphone" "SPL_dB" "Frequency_Hz"]))

figMax = figure(Name="Configuration C maximum SPL",Position=[100 100 1000 500]);
semilogx(frequency,levelMax,LineWidth=1.5), grid on
xlabel("Frequency (Hz)"), ylabel("Maximum SPL (dB re 20 " + char(181) + "Pa)")
title("Configuration C, maximum SPL within the limits of the driver")
legend(names,Location="best")
exportgraphics(figMax,fullfile(folder,"ConfigurationCMaxSPL.png"),Resolution=150)
[peakMax,indexMax] = max(levelMax);
disp(table(names.',peakMax.',frequency(indexMax),VariableNames=["Microphone" "MaxSPL_dB" "Frequency_Hz"]))

figZ = figure(Name="Configuration C impedance",Position=[100 100 1000 600]);
tlZ = tiledlayout(figZ,2,1,TileSpacing="compact");
nexttile(tlZ)
semilogx(frequency,abs(impedance),LineWidth=1.5), grid on
ylabel("|Z| (\Omega)"), title("Configuration C, electrical impedance")
nexttile(tlZ)
semilogx(frequency,rad2deg(angle(impedance)),LineWidth=1.5), grid on
xlabel("Frequency (Hz)"), ylabel("Phase (deg)")
exportgraphics(figZ,fullfile(folder,"ConfigurationCImpedance.png"),Resolution=150)
