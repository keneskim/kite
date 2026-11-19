using System;
using System.Globalization;
using System.Reflection;
using System.Text;

static class UnityConsole
{
    static void Main(string[] args)
    {
        Console.OutputEncoding = new UTF8Encoding(false);
        CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo("fr-FR");
        Type game = typeof(UnityConsole).Assembly.GetType(args[0], true);
        MethodInfo start = game.GetMethod("Start", BindingFlags.Instance | BindingFlags.NonPublic);
        start.Invoke(Activator.CreateInstance(game), null);
    }
}
